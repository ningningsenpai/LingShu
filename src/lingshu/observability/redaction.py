from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+"),
    re.compile(
        r'''(?i)(["']?[a-z0-9_]*(?:api[_-]?key|token|secret|authorization)'''
        r'''["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)'''
    ),
    re.compile(r"(?i)\b(?:sk|ak)-[a-z0-9_\-]{8,}\b"),
)


def redact_secrets(value: str) -> str:
    """隐藏文本中的常见凭据形态，同时保留原有排版。"""
    text = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[已隐藏]", text)
        else:
            text = pattern.sub("[已隐藏]", text)
    return text


def redact_preview(value: str | None, limit: int = 240) -> str | None:
    """隐藏常见凭据形态，并限制列表接口暴露的文本长度。"""
    if not value:
        return None
    text = redact_secrets(value)
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}…"
