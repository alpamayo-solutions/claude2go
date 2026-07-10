"""`c2g doctor` — verify the whole pipeline once at the desk, before driving.

Triggers the macOS microphone permission prompt, downloads the Whisper model,
and does one Claude round-trip with the subscription login.
"""

from __future__ import annotations

import asyncio
import subprocess

import numpy as np

from .config import Config

OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


async def run_doctor(config: Config) -> int:
    failures = 0

    # 1. TTS voice
    from .tts import pick_best_german_voice

    voice = config.voice or pick_best_german_voice()
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if any(line.startswith(voice) for line in voices.splitlines()):
        quality = "Premium/Enhanced" if "(" in voice else "Standard — natürlichere Stimme via Systemeinstellungen → Bedienungshilfen → Gesprochene Inhalte laden"
        print(f"{OK} TTS-Stimme »{voice}« ({quality})")
    else:
        print(f"{FAIL} TTS-Stimme »{voice}« fehlt (say -v '?' zeigt Alternativen)")
        failures += 1

    # 2. Microphone
    import sounddevice as sd

    from .audio import MicrophoneError, find_input_device

    default_input = sd.query_devices(kind="input")["name"]
    if "blackhole" in default_input.lower():
        print(f"{WARN} Standard-Input ist {default_input} (virtuell) — c2g wählt deshalb gezielt »{config.mic_device}«")
    try:
        device = find_input_device(config.mic_device)
        print(f"{OK} Mikrofon gefunden: {sd.query_devices(device)['name']}")
    except MicrophoneError as exc:
        print(f"{FAIL} {exc}")
        return failures + 1

    # 3. Record 3s + STT (this triggers the macOS mic-permission prompt)
    print("  Aufnahme: sag jetzt bitte einen Satz (3 Sekunden) …")
    try:
        recording = sd.rec(
            int(3 * config.sample_rate),
            samplerate=config.sample_rate,
            channels=1,
            dtype="int16",
            device=device,
        )
        sd.wait()
    except Exception as exc:  # noqa: BLE001 — diagnostics, not tracebacks
        print(f"{FAIL} Aufnahme fehlgeschlagen: {exc}")
        return failures + 1
    level = float(np.abs(recording).mean())
    if level < 5:
        print(f"{FAIL} Aufnahme ist praktisch still (Level {level:.1f}) — Mikrofonberechtigung fehlt? "
              "Systemeinstellungen → Datenschutz → Mikrofon → Terminal erlauben")
        failures += 1
    else:
        print(f"{OK} Mikrofon liefert Signal (Level {level:.1f})")

    print("  Lade Whisper-Modell (einmalig ggf. Download) …")
    from .stt import Transcriber

    transcriber = Transcriber(config.whisper_model, config.stt_language)
    transcript = transcriber.transcribe_sync(recording[:, 0].astype(np.float32) / 32768.0)
    if transcript.text:
        confidence = "sicher" if transcript.confident else ("brauchbar" if transcript.usable else "unsicher")
        print(f"{OK} Verstanden ({confidence}): »{transcript.text}«")
    else:
        print(f"{WARN} Nichts verstanden — bei stiller Aufnahme normal")

    # 4. Claude round-trip with subscription auth
    print("  Teste Claude-Session (Abo-Login) …")
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    reply = ""
    try:
        async for message in query(
            prompt="Antworte mit genau einem Wort: OK",
            options=ClaudeAgentOptions(model="haiku", max_turns=1),
        ):
            if isinstance(message, AssistantMessage):
                reply = " ".join(b.text for b in message.content if isinstance(b, TextBlock))
        print(f"{OK} Claude antwortet: »{reply.strip()}«")
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} Claude-Session fehlgeschlagen: {exc}")
        failures += 1

    # 5. TTS audible check
    proc = await asyncio.create_subprocess_exec(
        "say", "-v", voice, "-r", str(config.speech_rate),
        "Claude to go ist einsatzbereit.",
    )
    await proc.wait()

    print("\nAlles bereit." if failures == 0 else f"\n{failures} Problem(e) — siehe oben.")
    return failures
