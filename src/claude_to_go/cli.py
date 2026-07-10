"""`c2g` entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .config import Config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c2g",
        description="Claude-to-go: hands-free voice layer on top of Claude Code.",
    )
    parser.add_argument("--cwd", type=Path, default=None, help="Projektverzeichnis (Default: aktuelles)")
    parser.add_argument("--model", default=None, help="Modell-Override (z.B. opus, sonnet)")
    parser.add_argument("--continue", dest="cont", action="store_true", help="letzte Session fortsetzen (mit gesprochenem Recap)")
    parser.add_argument("--typed", action="store_true", help="tippen statt sprechen (Ausgabe weiterhin per Stimme)")
    parser.add_argument("--send", default=None, metavar="TEXT", help="eine Nachricht senden, Antwort ausgeben, beenden")
    parser.add_argument("--phone", action="store_true", help="iPhone als Mikrofon und Lautsprecher (PWA-Frontend)")
    parser.add_argument("--port", type=int, default=None, help="Port fürs Phone-Frontend (Default 8443)")
    parser.add_argument("--phone-http", action="store_true", help="Phone-Frontend ohne TLS (nur localhost-Tests)")
    parser.add_argument("--mute", action="store_true", help="keine Sprachausgabe (nur Konsole)")
    parser.add_argument("--no-log", action="store_true", help="kein Fahrtenprotokoll schreiben")
    parser.add_argument("--mic", default=None, help="Mikrofon-Name (Substring)")
    parser.add_argument("--voice", default=None, help="TTS-Stimme (Default: beste deutsche Stimme)")
    parser.add_argument("--whisper-model", default=None, help="Whisper-Modell (Default: small)")
    parser.add_argument("command", nargs="?", choices=["doctor"], help="doctor: Setup prüfen")
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config()
    if args.cwd:
        config.cwd = args.cwd.expanduser().resolve()
    if args.model:
        config.model = args.model
    config.continue_conversation = args.cont
    config.typed = args.typed
    config.send_once = args.send
    config.mute = args.mute
    config.phone = args.phone
    config.phone_http = args.phone_http
    if args.port:
        config.phone_port = args.port
    if args.no_log:
        config.log_dir = None
    if args.mic:
        config.mic_device = args.mic
    if args.voice:
        config.voice = args.voice
    if args.whisper_model:
        config.whisper_model = args.whisper_model
    return config


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    modes = [bool(args.send), args.typed, args.phone]
    if sum(modes) > 1:
        parser.error("--send, --typed und --phone schließen sich gegenseitig aus")

    # A stray API key would silently switch billing from the subscription to
    # pay-as-you-go API rates — never allow that in this wrapper.
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        print("Hinweis: ANTHROPIC_API_KEY entfernt — c2g nutzt bewusst nur den Abo-Login.")

    config = _config_from_args(args)

    if args.command == "doctor":
        from .doctor import run_doctor

        sys.exit(asyncio.run(run_doctor(config)))

    from .app import App

    # --send is non-interactive: risky actions are auto-denied instead of
    # asking questions nobody can answer.
    app = App(config, interactive=not config.send_once)
    try:
        if config.send_once:
            asyncio.run(app.run_send_once(config.send_once))
        elif config.typed:
            asyncio.run(app.run_typed())
        elif config.phone:
            asyncio.run(app.run_phone())
        else:
            asyncio.run(app.run_voice())
    except KeyboardInterrupt:
        print("\nTschüss.")


if __name__ == "__main__":
    main()
