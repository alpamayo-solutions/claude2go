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

    from .i18n import get_strings
    from .tts import pick_best_voice

    strings = get_strings(config.language)
    print(f"Language: {strings.code}")

    # 1. TTS voice
    voice = config.voice or pick_best_voice(strings.voice_locale, strings.fallback_voice)
    # Fixed argv, macOS system tool ("say"), no user input.
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout  # nosec B603 B607
    if any(line.startswith(voice) for line in voices.splitlines()):
        quality = "Premium/Enhanced" if "(" in voice else "Standard — for a more natural voice, download one via System Settings → Accessibility → Spoken Content"
        print(f"{OK} TTS voice “{voice}” ({quality})")
    else:
        print(f"{FAIL} TTS voice “{voice}” missing (say -v '?' shows alternatives)")
        failures += 1

    # 2. Microphone
    import sounddevice as sd

    from .audio import MicrophoneError, find_input_device

    default_input = sd.query_devices(kind="input")["name"]
    if "blackhole" in default_input.lower():
        print(f"{WARN} Default input is {default_input} (virtual) — c2g therefore explicitly selects “{config.mic_device}”")
    try:
        device = find_input_device(config.mic_device)
        print(f"{OK} Microphone found: {sd.query_devices(device)['name']}")
    except MicrophoneError as exc:
        print(f"{FAIL} {exc}")
        return failures + 1

    # 3. Record 3s + STT (this triggers the macOS mic-permission prompt)
    print("  Recording: please say a sentence now (3 seconds) …")
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
        print(f"{FAIL} Recording failed: {exc}")
        return failures + 1
    level = float(np.abs(recording).mean())
    if level < 5:
        print(f"{FAIL} Recording is practically silent (level {level:.1f}) — microphone permission missing? "
              "System Settings → Privacy → Microphone → allow Terminal")
        failures += 1
    else:
        print(f"{OK} Microphone delivers signal (level {level:.1f})")

    print("  Loading Whisper model (one-time download if needed) …")
    from .stt import Transcriber

    transcriber = Transcriber(config.whisper_model, strings.stt_language, strings.stt_prompt)
    transcript = transcriber.transcribe_sync(recording[:, 0].astype(np.float32) / 32768.0)
    if transcript.text:
        confidence = "confident" if transcript.confident else ("usable" if transcript.usable else "uncertain")
        print(f"{OK} Understood ({confidence}): “{transcript.text}”")
    else:
        print(f"{WARN} Nothing understood — normal for a silent recording")

    # 4. Claude round-trip with subscription auth
    print("  Testing Claude session (subscription login) …")
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    reply = ""
    try:
        async for message in query(
            prompt="Antworte mit genau einem Wort: OK",
            options=ClaudeAgentOptions(model="haiku", max_turns=1),
        ):
            if isinstance(message, AssistantMessage):
                reply = " ".join(b.text for b in message.content if isinstance(b, TextBlock))
        print(f"{OK} Claude replies: “{reply.strip()}”")
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} Claude session failed: {exc}")
        failures += 1

    # 5. TTS audible check
    proc = await asyncio.create_subprocess_exec(
        "say", "-v", voice, "-r", str(config.speech_rate),
        "Claude to go is ready.",
    )
    await proc.wait()

    print("\nAll set." if failures == 0 else f"\n{failures} problem(s) — see above.")
    return failures
