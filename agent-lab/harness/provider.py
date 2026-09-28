"""Provider normalization for local and optional OpenAI-compatible models."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


LOCAL_PROVIDER = "local"
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
PROVIDER_NAMES = {LOCAL_PROVIDER, OPENAI_COMPATIBLE_PROVIDER}
DEFAULT_REMOTE_ENDPOINT = "https://api.openai.com/v1/chat/completions"


def normalize_provider(value: Any) -> str:
    raw = str(value or LOCAL_PROVIDER).strip().lower().replace("-", "_")
    aliases = {
        "api": OPENAI_COMPATIBLE_PROVIDER,
        "openai": OPENAI_COMPATIBLE_PROVIDER,
        "remote": OPENAI_COMPATIBLE_PROVIDER,
        "openai_compatible": OPENAI_COMPATIBLE_PROVIDER,
    }
    normalized = aliases.get(raw, raw)
    if normalized not in PROVIDER_NAMES:
        raise ValueError(f"unsupported provider: {value}")
    return normalized


def normalize_endpoint(value: Any, *, provider: Any = OPENAI_COMPATIBLE_PROVIDER) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        raise ValueError("an API endpoint is required for the remote provider")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API endpoint must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API endpoint cannot contain credentials, a query string, or a fragment")
    return endpoint


def normalize_model(value: Any, *, provider: Any = OPENAI_COMPATIBLE_PROVIDER) -> str:
    model = str(value or "").strip()
    if not model:
        raise ValueError("a model name is required for the remote provider")
    if len(model) > 300:
        raise ValueError("model name is too long")
    return model


def normalize_provider_config(config: Any) -> dict[str, Any]:
    value = dict(config) if isinstance(config, dict) else {}
    provider = normalize_provider(value.get("provider"))
    value["provider"] = provider
    if provider == OPENAI_COMPATIBLE_PROVIDER:
        value["endpoint"] = normalize_endpoint(value.get("endpoint"), provider=provider)
        value["model"] = normalize_model(value.get("model"), provider=provider)
    return value


def public_provider(config: Any, *, has_api_key: bool = False) -> dict[str, Any]:
    value = dict(config) if isinstance(config, dict) else {}
    provider = normalize_provider(value.get("provider"))
    return {
        "provider": provider,
        "label": "Local model" if provider == LOCAL_PROVIDER else "OpenAI-compatible API",
        "endpoint": str(value.get("endpoint") or ""),
        "model": str(value.get("model") or ""),
        "has_api_key": bool(has_api_key) if provider == OPENAI_COMPATIBLE_PROVIDER else False,
    }

