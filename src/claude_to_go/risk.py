"""Classify tool calls: execute silently or ask the driver for permission.

A spurious ask is annoying; a missed ask is dangerous. Patterns anchor
destructive commands to command position (start of line, after a separator,
inside sh -c, past env/wrapper prefixes) to cut false positives while catching
evasions like `xargs rm`, `git -C path push`, and `GIT_SSH_COMMAND=… git push`.

Each pattern maps to a language-neutral category key; the spoken summary is
rendered from the active language pack, so a raw shell command is never read
aloud at road noise. The raw command stays on the verdict for "details".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .i18n import Strings, get_strings

_DEFAULT = get_strings("de")

# Matches at command position: line start, after ; & | ( ` or $( etc.,
# inside sh/bash/zsh -c '...' bodies, and past env-assignment/wrapper prefixes.
_CMD = (
    r"(?:^|[;&|`(]\s*|\bxargs\s+(?:-\S+\s+)*|\b(?:sh|bash|zsh)\s+(?:-\S+\s+)*[\"'])"
    r"(?:(?:env|command|nohup|time|builtin|exec)\s+"
    r"|[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)*"
)
# Skips options between `git` and its subcommand: `git -C /repo push` matches,
# `git log --grep 'push'` does not.
_GIT = r"git\s+(?:-\S+(?:\s+\S+)?\s+)*"


def _git_push_detail(command: str) -> str:
    args = re.search(r"push\s+(.{0,60})", command)
    return f": {args.group(1).strip()}" if args and args.group(1).strip() else ""


def _rm_detail(command: str) -> str:
    args = re.search(r"\brm\w*\s+(?:-\S+\s+)*(.{0,60})", command)
    return f": {args.group(1).strip()}" if args and args.group(1).strip() else ""


# (pattern, category_key, detail_fn|None)
_RISKY_BASH: list[tuple[str, str, object]] = [
    (rf"{_CMD}{_GIT}push\b", "git_push", _git_push_detail),
    (rf"{_CMD}{_GIT}reset\s+--hard\b", "git_reset", None),
    (rf"{_CMD}{_GIT}clean\b", "git_clean", None),
    (rf"{_CMD}{_GIT}checkout\s+(--\s+)?\.(\s|$)", "git_checkout", None),
    (rf"{_CMD}{_GIT}restore\b", "git_restore", None),
    (rf"{_CMD}{_GIT}stash\s+(drop|clear)\b", "git_stash_drop", None),
    (rf"{_CMD}{_GIT}branch\s+-[dD]\b", "git_branch_delete", None),
    (rf"{_CMD}{_GIT}rebase\b", "git_rebase", None),
    (rf"{_CMD}rm\b", "rm", _rm_detail),
    (rf"{_CMD}rmdir\b", "rm", _rm_detail),
    (rf"{_CMD}sudo\b", "sudo", None),
    (rf"{_CMD}kill(all)?\b", "kill", None),
    (rf"{_CMD}pkill\b", "kill", None),
    (rf"{_CMD}docker\s+(push|rm|rmi|system\s+prune|compose\s+down|volume\s+rm)\b", "docker", None),
    (rf"{_CMD}(npm|uv|pip|poetry|twine)\s+publish\b", "publish", None),
    (rf"{_CMD}npm\s+unpublish\b", "unpublish", None),
    (rf"{_CMD}gh\s+pr\s+(create|merge|close)\b", "gh_pr", None),
    (rf"{_CMD}gh\s+(release|repo\s+(delete|edit))\b", "gh_admin", None),
    (rf"{_CMD}\S*deploy\S*\b", "deploy", None),
    (rf"{_CMD}find\b[^|;&]*-delete\b", "rm", _rm_detail),
    (rf"{_CMD}dd\b", "dd", None),
    (r"\bdrop\s+(table|database)\b", "db_drop", None),
    (r"\btruncate\s+(table\b|\S+\.)", "db_truncate", None),
    (rf"{_CMD}mkfs\b", "mkfs", None),
    (rf"{_CMD}(shutdown|reboot)\b", "reboot", None),
    (rf"{_CMD}crontab\b", "crontab", None),
    (rf"{_CMD}launchctl\b", "launchctl", None),
    (rf"{_CMD}alp\s+task\s+log-time\b", "platform_hours", None),
    (rf"{_CMD}alp\s+\S+\s+(publish|propose\S*)\b", "platform_publish", None),
    (rf"{_CMD}mail\b", "mail", None),
    (rf"{_CMD}curl\b[^|;&]*(\s-X\s*(POST|PUT|DELETE|PATCH)|--request\s+(POST|PUT|DELETE|PATCH)|\s-d\b|\s--data\b)", "http_write", None),
]
_RISKY_BASH_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), cat, fn) for p, cat, fn in _RISKY_BASH
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
    spoken_summary: str  # localized category description for TTS
    raw: str = ""        # full command/tool detail for the "details" request


def _shorten(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _phrase(strings: Strings, category: str, detail: str = "") -> str:
    template = strings.risk_phrases.get(category, category)
    if "{detail}" in template:
        return template.format(detail=detail)
    return template


def classify(tool_name: str, tool_input: dict, strings: Strings = _DEFAULT) -> Verdict:
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for rx, category, detail_fn in _RISKY_BASH_COMPILED:
            if rx.search(command):
                detail = detail_fn(command) if detail_fn else ""
                return Verdict(True, _phrase(strings, category, detail), raw=_shorten(command))
        return Verdict(False, "")

    if tool_name in _SAFE_TOOLS:
        return Verdict(False, "")

    if tool_name.startswith("mcp__"):
        pretty = tool_name.split("__")[-1].replace("_", " ")
        if _MCP_WRITE_HINTS.search(tool_name):
            return Verdict(True, _phrase(strings, "mcp_write", pretty),
                           raw=_shorten(f"{tool_name} {tool_input}"))
        return Verdict(False, "")

    # Unknown tool: be safe, ask.
    return Verdict(True, _phrase(strings, "unknown_tool", tool_name),
                   raw=_shorten(f"{tool_name} {tool_input}"))
