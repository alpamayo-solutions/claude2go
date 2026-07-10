"""Classify tool calls: execute silently or ask the driver for permission.

A spurious ask is annoying; a missed ask is dangerous. Patterns therefore
anchor destructive commands to command position (start of line or after a
separator) to cut false positives, while catching common evasions like
`xargs rm` and `git -C path push`.

Spoken summaries are CATEGORY-based German ("auf Git pushen: origin main") —
a raw shell command is unparseable at road noise. The raw command is kept on
the verdict for the "details" voice command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches at command position: line start, after ; & | ( ` or $( etc.,
# inside sh/bash/zsh -c '...' bodies, and past env-assignment/wrapper
# prefixes (`GIT_SSH_COMMAND=ssh git push`, `env time git push`).
_CMD = (
    r"(?:^|[;&|`(]\s*|\bxargs\s+(?:-\S+\s+)*|\b(?:sh|bash|zsh)\s+(?:-\S+\s+)*[\"'])"
    r"(?:(?:env|command|nohup|time|builtin|exec)\s+"
    r"|[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)*"
)
# Skips options (with optional values) between `git` and its subcommand, so
# `git -C /repo push` is caught but `git log --grep 'push'` is not.
_GIT = r"git\s+(?:-\S+(?:\s+\S+)?\s+)*"


def _git_push_summary(m: re.Match, command: str) -> str:
    args = re.search(r"push\s+(.{0,60})", command)
    target = f": {args.group(1).strip()}" if args and args.group(1).strip() else ""
    return f"auf Git pushen{target}"


def _rm_summary(m: re.Match, command: str) -> str:
    args = re.search(r"\brm\w*\s+(?:-\S+\s+)*(.{0,60})", command)
    what = f": {args.group(1).strip()}" if args and args.group(1).strip() else ""
    return f"Dateien löschen{what}"


# (pattern, spoken_summary) — summary is a string or fn(match, command) -> str
_RISKY_BASH: list[tuple[str, object]] = [
    (rf"{_CMD}{_GIT}push\b", _git_push_summary),
    (rf"{_CMD}{_GIT}reset\s+--hard\b", "den Git-Stand hart zurücksetzen"),
    (rf"{_CMD}{_GIT}clean\b", "untrackte Dateien wegräumen"),
    (rf"{_CMD}{_GIT}checkout\s+(--\s+)?\.(\s|$)", "alle lokalen Änderungen verwerfen"),
    (rf"{_CMD}{_GIT}restore\b", "lokale Änderungen verwerfen"),
    (rf"{_CMD}{_GIT}stash\s+(drop|clear)\b", "gestashte Änderungen löschen"),
    (rf"{_CMD}{_GIT}branch\s+-[dD]\b", "einen Branch löschen"),
    (rf"{_CMD}{_GIT}rebase\b", "einen Rebase durchführen"),
    (rf"{_CMD}rm\b", _rm_summary),
    (rf"{_CMD}rmdir\b", _rm_summary),
    (rf"{_CMD}sudo\b", "einen Befehl mit Root-Rechten ausführen"),
    (rf"{_CMD}kill(all)?\b", "einen Prozess beenden"),
    (rf"{_CMD}pkill\b", "Prozesse beenden"),
    (rf"{_CMD}docker\s+(push|rm|rmi|system\s+prune|compose\s+down|volume\s+rm)\b", "eine Docker-Aufräumaktion ausführen"),
    (rf"{_CMD}(npm|uv|pip|poetry|twine)\s+publish\b", "ein Paket veröffentlichen"),
    (rf"{_CMD}npm\s+unpublish\b", "ein Paket zurückziehen"),
    (rf"{_CMD}gh\s+pr\s+(create|merge|close)\b", "einen Pull Request bearbeiten"),
    (rf"{_CMD}gh\s+(release|repo\s+(delete|edit))\b", "eine GitHub-Verwaltungsaktion ausführen"),
    (rf"{_CMD}\S*deploy\S*\b", "ein Deployment starten"),
    (rf"{_CMD}find\b[^|;&]*-delete\b", _rm_summary),
    (rf"{_CMD}dd\b", "rohe Daten schreiben mit dd"),
    (r"\bdrop\s+(table|database)\b", "eine Datenbanktabelle löschen"),
    (r"\btruncate\s+(table\b|\S+\.)", "eine Tabelle leeren"),
    (rf"{_CMD}mkfs\b", "ein Dateisystem formatieren"),
    (rf"{_CMD}(shutdown|reboot)\b", "den Rechner neu starten"),
    (rf"{_CMD}crontab\b", "geplante Aufgaben ändern"),
    (rf"{_CMD}launchctl\b", "einen Systemdienst ändern"),
    (rf"{_CMD}alp\s+task\s+log-time\b", "Arbeitszeit auf der Plattform buchen"),
    (rf"{_CMD}alp\s+\S+\s+(publish|propose\S*)\b", "etwas auf der Plattform veröffentlichen"),
    (rf"{_CMD}mail\b", "eine E-Mail-Aktion ausführen"),
    (rf"{_CMD}curl\b[^|;&]*(\s-X\s*(POST|PUT|DELETE|PATCH)|--request\s+(POST|PUT|DELETE|PATCH)|\s-d\b|\s--data\b)", "Daten per HTTP senden"),
]
_RISKY_BASH_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), s) for p, s in _RISKY_BASH
]

# Builtin tools that never need a spoken confirmation.
_SAFE_TOOLS = {
    "Read", "Glob", "Grep", "Edit", "Write", "MultiEdit", "NotebookEdit",
    "WebFetch", "WebSearch", "TodoWrite", "Task", "Agent", "Skill",
    "SlashCommand", "KillShell", "BashOutput", "TaskOutput", "TaskStop",
    "ExitPlanMode", "ListMcpResources", "ReadMcpResource", "SendUserFile",
}

# MCP tool-name fragments that imply a write/side effect.
_MCP_WRITE_HINTS = re.compile(
    r"(send|create|delete|update|write|post|upload|publish|move|remove|"
    r"set_|log_|execute|submit|approve|merge|deploy)",
    re.IGNORECASE,
)


@dataclass
class Verdict:
    ask: bool
    spoken_summary: str  # short German category description for TTS
    raw: str = ""        # full command/tool detail for the "details" request


def _shorten(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def classify(tool_name: str, tool_input: dict) -> Verdict:
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for rx, summary in _RISKY_BASH_COMPILED:
            m = rx.search(command)
            if m:
                spoken = summary(m, command) if callable(summary) else summary
                return Verdict(True, spoken, raw=_shorten(command))
        return Verdict(False, "")

    if tool_name in _SAFE_TOOLS:
        return Verdict(False, "")

    if tool_name.startswith("mcp__"):
        pretty = tool_name.split("__")[-1].replace("_", " ")
        if _MCP_WRITE_HINTS.search(tool_name):
            return Verdict(True, f"die Plattform-Aktion {pretty} ausführen",
                           raw=_shorten(f"{tool_name} {tool_input}"))
        return Verdict(False, "")

    # Unknown tool: be safe, ask.
    return Verdict(True, f"das Werkzeug {tool_name} benutzen",
                   raw=_shorten(f"{tool_name} {tool_input}"))
