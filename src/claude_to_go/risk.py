"""Classify tool calls: execute silently or ask the driver for permission."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Bash commands that are destructive, irreversible, or outward-facing.
_RISKY_BASH = [
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bgit\s+checkout\s+\.(\s|$)",
    r"\bgit\s+branch\s+(-D|-d)\b",
    r"\bgit\s+rebase\b",
    r"\brm\s",
    r"\brmdir\b",
    r"\bsudo\b",
    r"\bkill(all)?\b",
    r"\bdocker\s+(push|rm|rmi|system\s+prune|compose\s+down)\b",
    r"\b(npm|uv|pip|poetry|twine)\s+publish\b",
    r"\bnpm\s+unpublish\b",
    r"\bgh\s+(pr\s+create|pr\s+merge|release|repo\s+delete)\b",
    r"\bdeploy\b",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\b",
    r"\bmkfs\b",
    r"\b(shutdown|reboot)\b",
    r"\bcrontab\b",
    r"\blaunchctl\b",
    r"\balp\s+task\s+log-time\b",
    r"\balp\s+\S+\s+(publish|propose\S*)\b",
    r"\bmail\b",
    r"\bcurl\b[^|]*\s-(X\s*(POST|PUT|DELETE|PATCH)|d\b|-data\b)",
]
_RISKY_BASH_RE = [re.compile(p, re.IGNORECASE) for p in _RISKY_BASH]

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
