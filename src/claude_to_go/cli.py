"""`c2g` entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .config import Config, apply_settings, load_settings
from .i18n import LANGUAGES


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c2g",
        description="Claude-to-go: hands-free voice layer on top of Claude Code.",
    )
    parser.add_argument("--cwd", type=Path, default=None, help="project directory (default: current)")
    parser.add_argument("--model", default=None, help="model override (e.g. opus, sonnet)")
    parser.add_argument("--lang", choices=sorted(LANGUAGES), default=None,
                        help="interaction language (default: from settings, else de)")
    parser.add_argument("--continue", dest="cont", action="store_true", help="resume last session (with spoken recap)")
    parser.add_argument("--resume", nargs="?", const="", default=None, metavar="SESSION_ID",
                        help="resume a specific session (without ID: latest in directory)")
    parser.add_argument("--typed", action="store_true", help="type instead of speak (output still spoken)")
    parser.add_argument("--send", default=None, metavar="TEXT", help="send one message, print the reply, exit")
    parser.add_argument("--phone", action="store_true", help="iPhone as microphone and speaker (PWA frontend)")
    parser.add_argument("--port", type=int, default=None, help="port for the phone frontend (default 8443)")
    parser.add_argument("--phone-http", action="store_true", help="phone frontend without TLS (localhost tests only)")
    parser.add_argument("--mute", action="store_true", help="no speech output (console only)")
    parser.add_argument("--no-log", action="store_true", help="do not write a drive log")
    parser.add_argument("--mic", default=None, help="microphone name (substring)")
    parser.add_argument("--voice", default=None, help="TTS voice (default: best voice for the language)")
    parser.add_argument("--whisper-model", default=None, help="Whisper model (default: small)")
    parser.add_argument("command", nargs="?", choices=["doctor"], help="doctor: check setup")
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config()
    # Precedence: built-in defaults < settings file < CLI flags.
    apply_settings(config, load_settings())

    if args.cwd:
        config.cwd = args.cwd.expanduser().resolve()
    if args.model:
        config.model = args.model
    if args.lang:
        config.language = args.lang
    config.continue_conversation = args.cont
    if args.resume is not None:
        if args.resume == "":       # bare --resume: most recent in cwd
            config.continue_conversation = True
        else:
            config.resume = args.resume
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
        parser.error("--send, --typed and --phone are mutually exclusive")
    if args.cont and args.resume:
        parser.error("--continue and --resume are mutually exclusive")

    # A stray API key would silently switch billing from the subscription to
    # pay-as-you-go API rates — never allow that in this wrapper.
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        print("Note: ANTHROPIC_API_KEY removed — c2g deliberately uses the subscription login only.")

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
        print("\nBye.")


if __name__ == "__main__":
    main()
