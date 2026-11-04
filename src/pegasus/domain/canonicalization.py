"""Versioned, deterministic intent encoding shared by policy and grant adapters."""

import hashlib
import json


def canonical(value: dict) -> bytes:
    """v1: JSON primitives, sorted keys, UTF-8, integer monetary amounts."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()
