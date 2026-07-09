"""Classify tool calls: execute silently or ask the driver for permission.

A spurious ask is annoying; a missed ask is dangerous. Patterns therefore
anchor destructive commands to command position (start of line or after a
separator) to cut false positives, while catching common evasions like
`xargs rm` and `git -C path push`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches at command position: line start, after ; & | ( ` or $( etc.
_CMD = r"(?:^|[;&|`(]\s*|\bxargs\s+(?:-\S+\s+)*)"
# Skips options (with optional values) between `git` and its subcommand, so
# `git -C /repo push` is caught but `git log --grep 'push'` is not.
_GIT = r"git\s+(?:-\S+(?:\s+\S+)?\s+)*"

_RISKY_BASH = [
    rf"{_CMD}{_GIT}push\b",
    rf"{_CMD}{_GIT}reset\s+--hard\b",
    rf"{_CMD}{_GIT}clean\b",
    rf"{_CMD}{_GIT}checkout\s+(--\s+)?\.(\s|$)",
    rf"{_CMD}{_GIT}restore\b",
    rf"{_CMD}{_GIT}stash\s+(drop|clear)\b",
    rf"{_CMD}{_GIT}branch\s+-[dD]\b",
    rf"{_CMD}{_GIT}rebase\b",
    rf"{_CMD}rm\b",
    rf"{_CMD}rmdir\b",
    rf"{_CMD}sudo\b",
    rf"{_CMD}kill(all)?\b",
    rf"{_CMD}pkill\b",
    rf"{_CMD}docker\s+(push|rm|rmi|system\s+prune|compose\s+down|volume\s+rm)\b",
    rf"{_CMD}(npm|uv|pip|poetry|twine)\s+publish\b",
    rf"{_CMD}npm\s+unpublish\b",
    rf"{_CMD}gh\s+(pr\s+(create|merge|close)|release|repo\s+(delete|edit))\b",
    rf"{_CMD}\S*deploy\S*\b",
    rf"{_CMD}find\b[^|;&]*-delete\b",
    rf"{_CMD}dd\b",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\s+(table\b|\S+\.)",
    rf"{_CMD}mkfs\b",
    rf"{_CMD}(shutdown|reboot)\b",
    rf"{_CMD}crontab\b",
    rf"{_CMD}launchctl\b",
    rf"{_CMD}alp\s+task\s+log-time\b",
    rf"{_CMD}alp\s+\S+\s+(publish|propose\S*)\b",
    rf"{_CMD}mail\b",
    rf"{_CMD}curl\b[^|;&]*(\s-X\s*(POST|PUT|DELETE|PATCH)|--request\s+(POST|PUT|DELETE|PATCH)|\s-d\b|\s--data\b)",
]
_RISKY_BASH_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _RISKY_BASH]

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
    spoken_summary: str  # short German description for TTS when asking


def _shorten(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def classify(tool_name: str, tool_input: dict) -> Verdict:
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if any(rx.search(command) for rx in _RISKY_BASH_RE):
            return Verdict(True, f"den Befehl {_shorten(command)} ausführen")
        return Verdict(False, "")

    if tool_name in _SAFE_TOOLS:
        return Verdict(False, "")

    if tool_name.startswith("mcp__"):
        pretty = tool_name.split("__")[-1].replace("_", " ")
        if _MCP_WRITE_HINTS.search(tool_name):
            return Verdict(True, f"die Plattform-Aktion {pretty} ausführen")
        return Verdict(False, "")

    # Unknown tool: be safe, ask.
    return Verdict(True, f"das Werkzeug {tool_name} benutzen")
