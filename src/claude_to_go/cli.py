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
    parser.add_argument("--continue", dest="cont", action="store_true", help="letzte Session im Verzeichnis fortsetzen")
    parser.add_argument("--typed", action="store_true", help="tippen statt sprechen (Ausgabe weiterhin per Stimme)")
    parser.add_argument("--send", default=None, metavar="TEXT", help="eine Nachricht senden, Antwort ausgeben, beenden")
    parser.add_argument("--mute", action="store_true", help="keine Sprachausgabe (nur Konsole)")
    parser.add_argument("--mic", default=None, help="Mikrofon-Name (Substring)")
    parser.add_argument("--voice", default=None, help="TTS-Stimme (Default: Anna)")
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
    if args.mic:
        config.mic_device = args.mic
    if args.voice:
        config.voice = args.voice
    if args.whisper_model:
        config.whisper_model = args.whisper_model
    return config


def main() -> None:
    args = _build_parser().parse_args()

    # A stray API key would silently switch billing from the subscription to
    # pay-as-you-go API rates — never allow that in this wrapper.
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        print("Hinweis: ANTHROPIC_API_KEY entfernt — c2g nutzt bewusst nur den Abo-Login.")

    config = _config_from_args(args)

    if args.command == "doctor":
        from .doctor import run_doctor

        sys.exit(asyncio.run(run_doctor(config)))

    from .app import App

    app = App(config)
    try:
        if config.send_once:
            asyncio.run(app.run_send_once(config.send_once))
        elif config.typed:
            asyncio.run(app.run_typed())
        else:
            asyncio.run(app.run_voice())
    except KeyboardInterrupt:
        print("\nTschüss.")


if __name__ == "__main__":
    main()
