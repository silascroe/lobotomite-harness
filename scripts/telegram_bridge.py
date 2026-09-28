#!/usr/bin/env python3
"""Bridge one private Telegram chat to the local Agent Lab session."""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "agent-lab" / "telegram-bridge-state.json"
LOCAL_API = "http://127.0.0.1:8787"
TOKEN_ENV = "LLMTESTING_TELEGRAM_BOT_TOKEN"
MAX_TELEGRAM_MESSAGE = 3900
REPLY_TIMEOUT_SECONDS = 300


class BridgeError(Exception):
    """A recoverable bridge error."""


def token_value() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise BridgeError(
            f"{TOKEN_ENV} is missing. Run scripts/install-telegram-bridge.ps1 once, "
            "or start the foreground bridge from a shell where the token is present."
        )
    return token


def redact(value: object, token: str | None = None) -> str:
    text = str(value)
    if token:
        text = text.replace(token, "<redacted>")
    return text


def json_request(url: str, payload: dict[str, Any] | None = None, *, timeout: float = 30) -> Any:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise BridgeError(redact(exc, os.environ.get(TOKEN_ENV))) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"invalid JSON response from {url}: {raw[:300]}") from exc


def local_call(path: str, payload: dict[str, Any] | None = None, *, timeout: float = 30) -> dict[str, Any]:
    result = json_request(f"{LOCAL_API}{path}", payload, timeout=timeout)
    if not isinstance(result, dict):
        raise BridgeError(f"unexpected local API response for {path}")
    if result.get("error") and result.get("status") == "error":
        raise BridgeError(str(result["error"]))
    return result


def telegram_call(method: str, payload: dict[str, Any] | None = None, *, timeout: float = 40) -> Any:
    token = token_value()
    result = json_request(
        f"https://api.telegram.org/bot{token}/{method}",
        payload or {},
        timeout=timeout,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        description = result.get("description", "unknown Telegram API error") if isinstance(result, dict) else result
        raise BridgeError(redact(description, token))
    return result.get("result")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"could not read {STATE_PATH}: {exc}") from exc
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def send_message(chat_id: int, text: str) -> None:
    text = text.strip() or "(empty response)"
    for start in range(0, len(text), MAX_TELEGRAM_MESSAGE):
        telegram_call(
            "sendMessage",
            {"chat_id": chat_id, "text": text[start : start + MAX_TELEGRAM_MESSAGE]},
            timeout=30,
        )


def create_agent_session() -> str:
    state = local_call("/api/sessions", {})
    session_id = state.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise BridgeError("Agent Lab did not return a session id")
    return session_id


def session_state(session_id: str) -> dict[str, Any]:
    return local_call(f"/api/sessions/{urllib.parse.quote(session_id, safe='')}")


def ensure_agent_session(state: dict[str, Any]) -> str:
    current = state.get("session_id")
    if isinstance(current, str) and current:
        try:
            session_state(current)
            return current
        except BridgeError:
            pass
    current = create_agent_session()
    state["session_id"] = current
    save_state(state)
    return current


def wait_for_agent_reply(session_id: str, previous_count: int) -> str:
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        state = session_state(session_id)
        if state.get("status") == "error":
            raise BridgeError(str(state.get("last_error") or "Agent Lab session failed"))
        conversation = state.get("conversation", [])
        if not state.get("busy") and isinstance(conversation, list) and len(conversation) > previous_count:
            for message in reversed(conversation):
                if isinstance(message, dict) and message.get("role") == "assistant":
                    content = str(message.get("content") or "").strip()
                    if content:
                        return content
            raise BridgeError("Agent Lab finished without an assistant response")
    raise BridgeError("Agent Lab did not finish within five minutes")


def ask_agent(state: dict[str, Any], text: str) -> str:
    session_id = ensure_agent_session(state)
    before = session_state(session_id)
    previous_count = len(before.get("conversation", []))
    local_call(
        f"/api/sessions/{urllib.parse.quote(session_id, safe='')}/messages",
        {"content": text},
    )
    return wait_for_agent_reply(session_id, previous_count)


def reset_agent(state: dict[str, Any]) -> str:
    state["session_id"] = create_agent_session()
    save_state(state)
    return state["session_id"]


def drain_updates() -> int:
    updates = telegram_call("getUpdates", {"offset": -1, "limit": 1, "timeout": 0}, timeout=10)
    if not isinstance(updates, list) or not updates:
        return 0
    return int(updates[-1].get("update_id", -1)) + 1


def private_message(update: dict[str, Any]) -> tuple[int, str] | None:
    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    try:
        chat_id = int(chat["id"])
    except (KeyError, TypeError, ValueError):
        return None
    return chat_id, message["text"].strip()


def main() -> int:
    token_value()
    bot = telegram_call("getMe")
    username = bot.get("username", "the bot") if isinstance(bot, dict) else "the bot"
    state = load_state()
    paired_chat = state.get("chat_id")
    try:
        paired_chat = int(paired_chat) if paired_chat is not None else None
    except (TypeError, ValueError):
        paired_chat = None

    print(f"Telegram bot verified: @{username}", flush=True)
    offset = drain_updates()
    pairing_code = f"{secrets.randbelow(1_000_000):06d}"
    if paired_chat is None:
        print(f"Pairing code: {pairing_code}", flush=True)
        print(f"Open @{username} and send: /pair {pairing_code}", flush=True)
    else:
        try:
            send_message(paired_chat, "Agent Lab bridge online. Send a message, /reset, or /status.")
        except BridgeError as exc:
            print(f"Could not notify the paired chat: {exc}", file=sys.stderr, flush=True)

    while True:
        try:
            updates = telegram_call(
                "getUpdates",
                {"offset": offset, "timeout": 25, "allowed_updates": ["message"]},
                timeout=40,
            )
            if not isinstance(updates, list):
                continue
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                incoming = private_message(update)
                if incoming is None:
                    continue
                chat_id, text = incoming

                if paired_chat is None:
                    if text == f"/pair {pairing_code}":
                        paired_chat = chat_id
                        state["chat_id"] = chat_id
                        save_state(state)
                        ensure_agent_session(state)
                        send_message(chat_id, "Paired. This private chat now controls your local Agent Lab.")
                    continue

                if chat_id != paired_chat:
                    continue
                if text == "/start":
                    send_message(chat_id, "Connected to your local Agent Lab. Send a prompt or use /reset.")
                    continue
                if text == "/status":
                    session_id = ensure_agent_session(state)
                    current = session_state(session_id)
                    send_message(
                        chat_id,
                        f"Agent Lab is {current.get('status', 'unknown')}; "
                        f"model: {current.get('model', 'local model')}; "
                        f"model calls: {current.get('model_calls', 0)}.",
                    )
                    continue
                if text == "/reset":
                    reset_agent(state)
                    send_message(chat_id, "Started a fresh local agent conversation.")
                    continue
                if not text:
                    continue

                telegram_call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=20)
                try:
                    reply = ask_agent(state, text)
                except BridgeError as exc:
                    reply = f"Local agent error: {exc}"
                send_message(chat_id, reply)
        except KeyboardInterrupt:
            print("\nTelegram bridge stopped.", flush=True)
            return 0
        except BridgeError as exc:
            print(f"Bridge error: {exc}. Retrying in 5 seconds.", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())

