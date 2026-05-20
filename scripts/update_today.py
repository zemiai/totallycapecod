"""Update data/today.json — daily Cape Cod events via LLM extraction.

Strategy: fetch a small set of source pages, hand the HTML to Claude, ask for
clean JSON events for today's date. Slow path; runs once daily (plus a midday
refresh). Skipped automatically if ANTHROPIC_API_KEY is absent — in that case
the file stays whatever it was, and the safe_write guard keeps yesterday's
data rather than wiping it.

Source URLs are kept short. Add carefully — every URL adds API tokens.

Runs daily 5:30 AM ET (+ 11 AM refresh) via update-today.yml.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_existing, safe_write

OUT = Path(__file__).parent.parent / "data" / "today.json"

# Add real source URLs as they're confirmed. Start small.
SOURCES = [
    # "https://www.capecodchamber.org/events/",
    # "https://www.thebeachcomber.com/calendar",
]

CATEGORIES = ["music", "happy_hour", "free_event", "family", "food_deal", "drive_in", "farmers_market", "trivia", "art"]


def fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": "totallycapecod/1.0"}, timeout=30)
    r.raise_for_status()
    return r.text


def extract_with_claude(htmls: dict[str, str], target_date: str, api_key: str) -> list[dict]:
    """Send HTML chunks to Claude, ask for normalized event JSON."""
    combined = "\n\n---\n\n".join(
        f"# Source: {url}\n\n{html[:30000]}" for url, html in htmls.items()
    )
    prompt = f"""You are an event extractor for Cape Cod, MA. From the HTML below, return a JSON array
of events happening on {target_date}. For each event return keys:
  id (kebab-case slug), tag (emoji + UPPER label, e.g. "🎵 LIVE MUSIC"),
  category (one of: {", ".join(CATEGORIES)}),
  time ("9:00 PM"), title, venue, town, info, price, lat, lng, img (optional), source_url.

Return ONLY the JSON array, no prose. Empty array if nothing today.

HTML:
{combined}"""

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["content"][0]["text"].strip()
    # Strip ```json fences if Claude added them
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[hermes] no ANTHROPIC_API_KEY — skipping today.json refresh (existing file kept)")
        sys.exit(0)
    if not SOURCES:
        print("[hermes] no source URLs configured in update_today.py — skipping")
        sys.exit(0)

    target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    htmls = {}
    for url in SOURCES:
        try:
            htmls[url] = fetch_html(url)
        except Exception as e:
            print(f"[hermes] failed to fetch {url}: {e}", file=sys.stderr)

    if not htmls:
        print("[hermes] no sources fetched successfully — aborting", file=sys.stderr)
        sys.exit(1)

    events = extract_with_claude(htmls, target_date, api_key)
    print(f"[hermes] extracted {len(events)} events for {target_date}")

    payload = {"date": target_date, "events": events}
    safe_write(OUT, payload, count_key="events", min_ratio=0.5)


if __name__ == "__main__":
    main()
