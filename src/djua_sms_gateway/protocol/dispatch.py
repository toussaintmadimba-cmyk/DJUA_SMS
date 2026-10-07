"""Explicit protocol dispatch without changing legacy D1 semantics."""

from __future__ import annotations

from .d2 import D2ProtocolError


def detect_protocol(raw_message: str) -> str:
    if raw_message.startswith("D1,"):
        return "D1"
    if raw_message.startswith("D2T,"):
        return "D2T"
    if raw_message.startswith("D2E,"):
        return "D2E"
    raise D2ProtocolError(
        "UNSUPPORTED_PROTOCOL",
        "expected D1, D2T, D2T2 or D2E",
        "protocol",
    )
