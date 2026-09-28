"""Deterministic context-window management for the local agent.

The harness keeps the complete transcript for recovery and inspection.  This
module only shapes the request sent to the model when that transcript grows
past the configured request budget.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


Message = dict[str, Any]


@dataclass(frozen=True)
class ContextResult:
    """The model-facing request plus inspectable compaction metadata."""

    messages: list[Message]
    compacted: bool
    max_tokens: int
    before_tokens: int
    after_tokens: int
    dropped_messages: int
    summary_lines: int

    def metadata(self) -> dict[str, Any]:
        return {
            "compacted": self.compacted,
            "max_tokens": self.max_tokens,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "dropped_messages": self.dropped_messages,
            "message_count": len(self.messages),
            "summary_lines": self.summary_lines,
        }


def estimate_tokens(messages: Iterable[Message], *, chars_per_token: float = 4.0) -> int:
    """Return a conservative, tokenizer-independent token estimate.

    Local endpoints can use different tokenizers.  A stable character-based
    estimate is sufficient for deciding when to compact and keeps this layer
    independent from a model-specific tokenizer package.
    """

    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    encoded = json.dumps(
        list(messages),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return max(1, math.ceil(len(encoded) / chars_per_token)) if encoded != "[]" else 0


def build_context(
    messages: list[Message],
    *,
    max_tokens: int,
    recent_messages: int = 12,
    chars_per_token: float = 4.0,
) -> ContextResult:
    """Build a bounded request view without mutating the durable transcript.

    The first system message is retained verbatim.  Older observable messages
    become a short operational summary, while the newest messages are kept as
    individual turns whenever the budget permits.  If the budget is unusually
    small, older recent turns are compacted or removed before the newest turn
    is touched.
    """

    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if recent_messages < 1:
        raise ValueError("recent_messages must be at least one")
    if not isinstance(messages, list):
        raise TypeError("messages must be a list")

    normalized = _validate_messages(messages)
    before_tokens = estimate_tokens(normalized, chars_per_token=chars_per_token)
    if before_tokens <= max_tokens:
        return ContextResult(
            messages=[dict(message) for message in normalized],
            compacted=False,
            max_tokens=max_tokens,
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            dropped_messages=0,
            summary_lines=0,
        )

    system: Message | None = None
    body = normalized
    if normalized and normalized[0].get("role") == "system":
        system = dict(normalized[0])
        body = normalized[1:]

    tail = [dict(message) for message in body[-recent_messages:]]
    omitted = body[: max(0, len(body) - len(tail))]
    summary, summary_lines = _build_summary(omitted)
    fitted, additional_drops = _fit_to_budget(
        system=system,
        summary=summary,
        tail=tail,
        max_tokens=max_tokens,
        chars_per_token=chars_per_token,
    )
    dropped_messages = len(omitted) + additional_drops
    after_tokens = estimate_tokens(fitted, chars_per_token=chars_per_token)
    if after_tokens > max_tokens:
        raise ValueError(
            "context budget is smaller than the required system and latest message"
        )

    return ContextResult(
        messages=fitted,
        compacted=True,
        max_tokens=max_tokens,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        dropped_messages=dropped_messages,
        summary_lines=summary_lines if summary else 0,
    )


def _validate_messages(messages: list[Message]) -> list[Message]:
    normalized: list[Message] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TypeError(f"message {index} must be an object")
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"message {index} must have a role")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        copied = dict(message)
        copied["role"] = role
        copied["content"] = content
        normalized.append(copied)
    return normalized


def _build_summary(messages: list[Message]) -> tuple[str, int]:
    if not messages:
        return "", 0

    lines = ["Earlier observable context:"]
    for message in messages:
        lines.append(f"- {_summarize_message(message)}")
    lines.append("Use the project files and the recent messages as authoritative.")
    return "\n".join(lines), len(lines) - 2


def _summarize_message(message: Message) -> str:
    role = str(message.get("role", "message"))
    content = str(message.get("content", ""))
    payload = _parse_json_object(content)

    if payload is not None:
        action = payload.get("action")
        if isinstance(action, str):
            details: list[str] = []
            args = payload.get("args")
            if isinstance(args, dict):
                for key in ("path", "command", "phase", "query", "status"):
                    value = args.get(key)
                    if value is not None:
                        details.append(f"{key}={_clip_scalar(value, 70)}")
            return _clip_text(f"{role} action {action} {' '.join(details)}", 180)

        tool = payload.get("tool")
        if isinstance(tool, str):
            result = payload.get("result")
            details = []
            if isinstance(result, dict):
                for key in ("ok", "path", "bytes", "status", "exit_code"):
                    value = result.get(key)
                    if value is not None:
                        details.append(f"{key}={_clip_scalar(value, 70)}")
            return _clip_text(f"{role} tool {tool} {' '.join(details)}", 180)

    flattened = re.sub(r"\s+", " ", content).strip()
    return _clip_text(f"{role}: {flattened}", 180)


def _parse_json_object(content: str) -> dict[str, Any] | None:
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _clip_scalar(value: Any, limit: int) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    return _clip_text(re.sub(r"\s+", " ", text), limit)


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _fit_to_budget(
    *,
    system: Message | None,
    summary: str,
    tail: list[Message],
    max_tokens: int,
    chars_per_token: float,
) -> tuple[list[Message], int]:
    """Fit the candidate while preserving the newest complete turns first."""

    working_system = dict(system) if system is not None else None
    working_tail = [dict(message) for message in tail]
    working_summary = summary
    additional_drops = 0

    def candidate() -> list[Message]:
        result: list[Message] = []
        if working_system is not None:
            result.append(dict(working_system))
        if working_summary:
            result.append({"role": "user", "content": working_summary})
        result.extend(dict(message) for message in working_tail)
        return result

    if estimate_tokens(candidate(), chars_per_token=chars_per_token) <= max_tokens:
        return candidate(), additional_drops

    # Older entries inside the recent slice are still useful as landmarks, but
    # their raw payloads should not crowd out the newest user/assistant turns.
    preserve_complete = min(2, len(working_tail))
    for index in range(max(0, len(working_tail) - preserve_complete)):
        working_tail[index]["content"] = _summarize_message(working_tail[index])

    # If the budget is still tight, retain only the newest two complete turns.
    while (
        estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens
        and len(working_tail) > preserve_complete
    ):
        working_tail.pop(0)
        additional_drops += 1

    # Trim the summary from the end.  Its heading and first landmarks are kept,
    # which makes compaction visible and keeps the most useful operation names.
    for limit in (1200, 800, 520, 360, 240, 160, 120, 96, 90, 80, 76):
        if estimate_tokens(candidate(), chars_per_token=chars_per_token) <= max_tokens:
            break
        working_summary = _clip_text(working_summary, limit)

    # Finally, preserve the latest turn(s) and shrink older retained content.
    if estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens:
        for index in range(max(0, len(working_tail) - preserve_complete)):
            working_tail[index]["content"] = _clip_text(
                working_tail[index]["content"],
                96,
            )

    while (
        estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens
        and len(working_tail) > 1
    ):
        working_tail.pop(0)
        additional_drops += 1

    if estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens:
        # This is an exceptional, tiny-budget fallback.  Keep the newest
        # message and progressively shorten its content.  The system role is
        # retained as an anchor, but its text may be clipped when a caller has
        # configured a budget smaller than the prompt itself.
        if working_tail:
            newest = working_tail[-1]
            for limit in (256, 160, 96, 64, 40, 24, 12, 4, 1):
                if estimate_tokens(candidate(), chars_per_token=chars_per_token) <= max_tokens:
                    break
                newest["content"] = _clip_text(str(newest.get("content", "")), limit)

    if working_system is not None and estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens:
        for limit in (4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 1):
            if estimate_tokens(candidate(), chars_per_token=chars_per_token) <= max_tokens:
                break
            working_system["content"] = _clip_text(str(working_system.get("content", "")), limit)

    if estimate_tokens(candidate(), chars_per_token=chars_per_token) > max_tokens:
        working_summary = ""

    return candidate(), additional_drops

