"""Persistent Claude Code session via the official Agent SDK.

Spawns the locally installed `claude` binary with the user's subscription
login — the same engine and settings as an interactive session.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from . import risk
from .config import Config
from .prompts import VOICE_STYLE

# async (spoken_summary) -> True (allow) / False (deny)
PermissionAsker = Callable[[str], Awaitable[bool]]


@dataclass
class TurnResult:
    text: str
    elapsed_s: float
    is_error: bool


class ClaudeSession:
    def __init__(
        self,
        config: Config,
        ask_permission: PermissionAsker,
        on_interjection_reply: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._ask_permission = ask_permission
        self._on_interjection_reply = on_interjection_reply
        self._client: ClaudeSDKClient | None = None
        self._unanswered_injections: list[str] = []
        self.working = False
        self.turn_started_at: float | None = None
        self.last_tool: str | None = None

    async def start(self) -> None:
        options = ClaudeAgentOptions(
            cwd=str(self._config.cwd),
            model=self._config.model,
            continue_conversation=self._config.continue_conversation,
            permission_mode="acceptEdits",
            setting_sources=["user", "project"],
            system_prompt={"type": "preset", "preset": "claude_code", "append": VOICE_STYLE},
            disallowed_tools=["AskUserQuestion"],
            can_use_tool=self._on_tool_permission,
            # The user's own settings allow-list (e.g. "Bash(*)") would silently
            # bypass can_use_tool. This hook forces risky calls back to "ask" so
            # the spoken permission gate always gets its turn.
            hooks={"PreToolUse": [HookMatcher(hooks=[self._pre_tool_hook])]},
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def stop(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def reconnect(self) -> None:
        """Recover from a dead CLI subprocess; resumes the same conversation."""
        try:
            await self.stop()
        except Exception:  # noqa: BLE001 — the old client may be beyond saving
            self._client = None
        self.working = False
        self._config.continue_conversation = True
        await self.start()

    async def interrupt(self) -> None:
        if self._client and self.working:
            await self._client.interrupt()

    async def inject(self, text: str) -> None:
        """Steer the RUNNING turn — like typing mid-turn in interactive Claude
        Code. Verified: the message is absorbed into the current turn and
        answered at the next step boundary (single ResultMessage)."""
        assert self._client is not None, "session not started"
        self._unanswered_injections.append(text)
        await self._client.query(text)

    def take_unanswered_injections(self) -> list[str]:
        """Injections the turn never got to (it ended first) — the caller
        should re-send them as regular messages."""
        pending, self._unanswered_injections = self._unanswered_injections, []
        return pending

    @property
    def status_de(self) -> str:
        if not self.working or self.turn_started_at is None:
            return "Ich bin bereit und warte auf dich."
        elapsed = int(time.monotonic() - self.turn_started_at)
        minutes, seconds = divmod(elapsed, 60)
        duration = f"{minutes} Minuten" if minutes else f"{seconds} Sekunden"
        tool = f", zuletzt {self.last_tool}" if self.last_tool else ""
        return f"Ich arbeite seit {duration}{tool}."

    async def send(self, text: str) -> TurnResult:
        """Send one user message and stream until the turn completes."""
        assert self._client is not None, "session not started"
        self.working = True
        self.turn_started_at = time.monotonic()
        self.last_tool = None
        final_text = ""
        is_error = False
        try:
            await self._client.query(text)
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    # Subagent (Task) side-chains stream through here too —
                    # their text must never become the spoken final answer.
                    if message.parent_tool_use_id:
                        continue
                    texts = [b.text for b in message.content if isinstance(b, TextBlock)]
                    if texts:
                        final_text = " ".join(texts)
                        # First text after a mid-turn interjection is its
                        # answer — surface it immediately, don't wait for
                        # the turn to finish.
                        if self._unanswered_injections and self._on_interjection_reply:
                            self._unanswered_injections.clear()
                            await self._on_interjection_reply(final_text)
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            self.last_tool = block.name
                            print(f"\033[2m  ⚙ {block.name}\033[0m", flush=True)
                elif isinstance(message, ResultMessage):
                    is_error = message.is_error
                    if not final_text and message.result:
                        final_text = message.result
        finally:
            self.working = False
        elapsed = time.monotonic() - self.turn_started_at
        return TurnResult(text=final_text, elapsed_s=elapsed, is_error=is_error)

    async def _pre_tool_hook(self, input_data, _tool_use_id, _context):
        tool_name = str(input_data.get("tool_name", ""))
        tool_input = dict(input_data.get("tool_input") or {})
        if risk.classify(tool_name, tool_input).ask:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": "Riskant — Fahrer muss per Stimme freigeben.",
                }
            }
        return {}

    async def _on_tool_permission(self, tool_name, tool_input, _context):
        verdict = risk.classify(tool_name, dict(tool_input or {}))
        if not verdict.ask:
            return PermissionResultAllow()
        allowed = await self._ask_permission(verdict.spoken_summary)
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=(
                "Der Fahrer hat diesen Schritt abgelehnt oder nicht geantwortet. "
                "Überspringe ihn, mach mit dem Rest weiter und erwähne es kurz "
                "in deiner Abschlussantwort."
            )
        )
