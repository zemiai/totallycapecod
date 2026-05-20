"""Shared IO utilities for Hermes cron scripts.

Conventions enforced here:
- every JSON file has {version, updated_at} envelope
- writes are validated against the previous file size to catch scraper failures
- timestamps are UTC ISO 8601 with Z suffix
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def now_iso() -> str:
    """Current UTC time in ISO 8601 with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_existing(path: str | Path) -> dict[str, Any] | None:
    """Load existing JSON or None if file is missing/invalid."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[hermes] WARNING: existing {path} is invalid JSON: {e}", file=sys.stderr)
        return None


def safe_write(
    path: str | Path,
    new_data: dict[str, Any],
    *,
    count_key: str | None = None,
    min_ratio: float = 0.5,
    stamp: bool = True,
) -> None:
    """Write new_data to path with validation guards.

    Args:
        path: target JSON file
        new_data: full payload to write (must be JSON-serializable)
        count_key: top-level list key to compare sizes against (e.g. 'events').
                   If None, compares total JSON string length instead.
        min_ratio: abort if new size < previous * min_ratio. Set to 0 to disable.
        stamp: if True, sets new_data['updated_at'] = now_iso() and ensures version='1.0'.

    Raises SystemExit(1) on validation failure — fails the cron run loudly.
    """
    p = Path(path)
    existing = read_existing(p)

    if stamp:
        new_data.setdefault("version", "1.0")
        new_data["updated_at"] = now_iso()

    # Validation guard: don't silently overwrite good data with garbage.
    if existing and min_ratio > 0:
        if count_key:
            old_n = len(existing.get(count_key, []))
            new_n = len(new_data.get(count_key, []))
            if old_n > 0 and new_n < old_n * min_ratio:
                print(
                    f"[hermes] ABORT: {path} {count_key} dropped from {old_n} to {new_n} "
                    f"(< {min_ratio:.0%} of previous). Refusing to overwrite.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            old_len = len(json.dumps(existing))
            new_len = len(json.dumps(new_data))
            if new_len < old_len * min_ratio:
                print(
                    f"[hermes] ABORT: {path} size dropped from {old_len}B to {new_len}B. "
                    f"Refusing to overwrite.",
                    file=sys.stderr,
                )
                sys.exit(1)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(new_data, indent=2) + "\n", encoding="utf-8")
    print(f"[hermes] wrote {path}")


def env(name: str, required: bool = True) -> str:
    """Read an env var, with a clear error if required and missing."""
    val = os.environ.get(name)
    if required and not val:
        print(f"[hermes] missing required env var: {name}", file=sys.stderr)
        sys.exit(2)
    return val or ""
