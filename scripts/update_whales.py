"""Update data/whales.json — prune sightings older than 7 days.

This script does NOT add sightings. Sightings come from:
  - the app's submitSighting() (stored client-side until webhook is wired)
  - manual edits to data/whales.json
  - future Twilio webhook from whale watch operators

The cron's job is to keep the file from growing forever by dropping stale entries.

Runs every 30 min during summer via update-whales.yml (cheap; mostly no-op).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_existing, safe_write

OUT = Path(__file__).parent.parent / "data" / "whales.json"
MAX_AGE_DAYS = 7


def main() -> None:
    existing = read_existing(OUT)
    if not existing:
        print("[hermes] data/whales.json missing — nothing to prune", file=sys.stderr)
        sys.exit(0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    keep = []
    for s in existing.get("recent_sightings", []):
        ts = s.get("reported_at", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt >= cutoff:
                keep.append(s)
        except Exception:
            # Bad/missing timestamp — keep it; let humans clean up
            keep.append(s)

    dropped = len(existing.get("recent_sightings", [])) - len(keep)
    existing["recent_sightings"] = keep
    print(f"[hermes] pruned {dropped} sightings older than {MAX_AGE_DAYS}d")

    # No min_ratio guard here — pruning is allowed to shrink the file substantially.
    safe_write(OUT, existing, count_key=None, min_ratio=0)


if __name__ == "__main__":
    main()
