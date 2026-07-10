"""Phone frontend: aiohttp server streaming mic audio in and TTS audio out.

The iPhone (Safari PWA, see phone/index.html) connects over one WebSocket:
  phone → mac : binary int16 16 kHz PCM chunks · {"type":"answer"|"stop"|"hello"|"tts_done"}
  mac → phone : {"type":"say","id","text"} + binary WAV · {"type":"earcon"} ·
                {"type":"state"|"user"|"assistant"|"note"|"permission"|"window"}

CarPlay/Bluetooth routes the phone's audio to the car speakers automatically.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from importlib import resources
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

from .audio import UtteranceSegmenter, Vad
from .config import Config
from .tts import render_wav, sanitize_for_speech, pick_best_german_voice


class RemoteSpeaker:
    """Speaker-compatible TTS sink that plays on the connected phone."""

    def __init__(self, server: "AudioServer", voice: str | None, rate: int, mute: bool) -> None:
        self._server = server
        self._voice = voice or pick_best_german_voice()
        self._rate = rate
        self._mute = mute
        self._lock = asyncio.Lock()
        self._say_id = 0
        self._done: asyncio.Event = asyncio.Event()
        self._speaking = False

    @property
    def speaking(self) -> bool:
        return self._speaking

    async def say(self, text: str, sanitize: bool = True) -> None:
        spoken = sanitize_for_speech(text) if sanitize else text.strip()
        if not spoken:
            return
        print(f"\033[36m🔊 {spoken}\033[0m", flush=True)
        if self._mute or not self._server.connected:
            return
        async with self._lock:
            wav = await render_wav(self._voice, self._rate, spoken)
            duration = max(0.5, (len(wav) - 44) / 2 / 22050)
            self._say_id += 1
            self._done = asyncio.Event()
            self._speaking = True
            try:
                await self._server.send_json({"type": "say", "id": self._say_id, "text": spoken})
                await self._server.send_bytes(wav)
                # The phone reports playback end; the timeout covers lost
                # clients and dead zones.
                await asyncio.wait_for(self._done.wait(), timeout=duration + 5.0)
            except (asyncio.TimeoutError, ConnectionError):
                pass
            finally:
                self._speaking = False

    def notify_done(self, say_id: int) -> None:
        if say_id == self._say_id:
            self._done.set()

    def stop(self) -> None:
        self._done.set()
        self._speaking = False
        self._server.schedule_json({"type": "tts_stop"})

    async def earcon(self, name: str) -> None:
        await self._server.send_json({"type": "earcon", "name": name})


class AudioServer:
    def __init__(self, config: Config, app, utterance_queue: asyncio.Queue) -> None:
        self._config = config
        self._app = app
        self._queue = utterance_queue
        self._ws: web.WebSocketResponse | None = None
        self._runner: web.AppRunner | None = None
        self.speaker = RemoteSpeaker(self, config.voice, config.speech_rate, config.mute)
        app.event_sink = self._on_app_event

    # ---------- lifecycle ----------

    async def start(self) -> None:
        web_app = web.Application()
        web_app.router.add_get("/", self._index)
        web_app.router.add_get("/manifest.json", self._manifest)
        web_app.router.add_get("/ws", self._ws_handler)
        self._runner = web.AppRunner(web_app)
        await self._runner.setup()

        ssl_ctx = None
        scheme = "http"
        if not self._config.phone_http:
            ssl_ctx = _ensure_tls(Path.home() / ".c2g" / "tls")
            if ssl_ctx is not None:
                scheme = "https"
            else:
                print("\033[33mTLS nicht verfügbar (openssl fehlt?) — HTTP-Modus; "
                      "Mikrofon funktioniert dann nur via localhost.\033[0m", flush=True)
        site = web.TCPSite(self._runner, "0.0.0.0", self._config.phone_port, ssl_context=ssl_ctx)
        await site.start()

        url = f"{scheme}://{_lan_ip()}:{self._config.phone_port}/"
        print(f"\n📱 Phone-Frontend: \033[1m{url}\033[0m", flush=True)
        _print_qr(url)
        if scheme == "https":
            print("(Selbstsigniertes Zertifikat — beim ersten Öffnen in Safari "
                  "»Details« → »Webseite öffnen« bestätigen.)\n", flush=True)

    async def stop(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._runner is not None:
            await self._runner.cleanup()

    # ---------- HTTP ----------

    async def _index(self, _request: web.Request) -> web.Response:
        html = resources.files("claude_to_go").joinpath("phone/index.html").read_text("utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _manifest(self, _request: web.Request) -> web.Response:
        return web.json_response({
            "name": "Claude to go",
            "short_name": "c2g",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a0c10",
            "theme_color": "#0a0c10",
        })

    # ---------- WebSocket ----------

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def send_json(self, payload: dict) -> None:
        if self.connected:
            try:
                await self._ws.send_str(json.dumps(payload, ensure_ascii=False))
            except ConnectionError:
                pass

    async def send_bytes(self, data: bytes) -> None:
        if self.connected:
            try:
                await self._ws.send_bytes(data)
            except ConnectionError:
                pass

    def schedule_json(self, payload: dict) -> None:
        asyncio.get_event_loop().create_task(self.send_json(payload))

    def _on_app_event(self, kind: str, fields: dict) -> None:
        self.schedule_json({"type": kind, **fields})

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()  # newest client wins (one driver, one phone)
        self._ws = ws
        print("\033[32m📱 Phone verbunden\033[0m", flush=True)

        segmenter = UtteranceSegmenter(
            vad=Vad(self._config.vad_aggressiveness, self._config.sample_rate),
            sample_rate=self._config.sample_rate,
            min_s=self._config.utterance_min_s,
            max_s=self._config.utterance_max_s,
            silence_end_ms=self._config.silence_end_ms,
            on_utterance=lambda t, u: self._queue.put_nowait((t, u)),
        )
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    segmenter.feed(np.frombuffer(msg.data, dtype=np.int16))
                elif msg.type == WSMsgType.TEXT:
                    await self._on_client_msg(json.loads(msg.data))
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            if self._ws is ws:
                self._ws = None
            print("\033[33m📱 Phone getrennt\033[0m", flush=True)
        return ws

    async def _on_client_msg(self, payload: dict) -> None:
        kind = payload.get("type")
        if kind == "hello":
            await self.send_json({
                "type": "state",
                "value": "working" if self._app.session.working else "idle",
            })
        elif kind == "tts_done":
            self.speaker.notify_done(int(payload.get("id", 0)))
        elif kind == "stop":
            asyncio.get_event_loop().create_task(self._app._do_stop())
        elif kind == "answer":
            # Big JA/NEIN touch buttons — always confident, never echo.
            value = str(payload.get("value", ""))[:200]
            asyncio.get_event_loop().create_task(
                self._app.handle_utterance(value, confident=True)
            )


# ---------- helpers ----------

def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


def _ensure_tls(tls_dir: Path):
    """Self-signed cert (getUserMedia requires a secure context). Returns an
    SSLContext or None if generation is impossible."""
    import ssl

    cert, key = tls_dir / "cert.pem", tls_dir / "key.pem"
    if not (cert.exists() and key.exists()):
        tls_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", str(key), "-out", str(cert), "-days", "825", "-nodes",
             "-subj", "/CN=claude-to-go",
             "-addext", f"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{_lan_ip()}"],
            capture_output=True,
        )
        if result.returncode != 0:
            return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


def _print_qr(url: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        pass
