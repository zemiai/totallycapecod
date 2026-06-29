"""Generate natural lighthouse-tour narration MP3s via ElevenLabs.

Reads data/lighthouses.json, synthesizes each entry's `script` to
audio/lighthouses/<slug>.mp3, sets the entry's `audio_url`, and writes the JSON
back. Idempotent: skips a lighthouse whose MP3 already exists (set FORCE=1 to
regenerate everything, e.g. after changing the voice).

The app (app/index.html) already plays audio_url when present and only falls back
to robotic browser TTS when it's missing — so once this runs, the tours are natural.

Run via .github/workflows/gen-lighthouse-audio.yml (ELEVENLABS_API_KEY secret),
or locally:  ELEVENLABS_API_KEY=sk_... python scripts/gen_lighthouse_audio.py
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
LH = ROOT / "data" / "lighthouses.json"
OUTDIR = ROOT / "audio" / "lighthouses"

KEY = os.environ.get("ELEVENLABS_API_KEY")
# Default voice "Rachel" (calm, clear narrator). Override with your own from the
# ElevenLabs voice library via the ELEVENLABS_VOICE_ID env/secret.
VOICE = os.environ.get("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM"
# turbo_v2_5 = 0.5 credits/char (the ~11k-char set fits the free tier). Switch to
# "eleven_multilingual_v2" for max quality if you're on a paid plan.
MODEL = os.environ.get("ELEVENLABS_MODEL") or "eleven_turbo_v2_5"
FORCE = os.environ.get("FORCE") == "1"


def synth(text: str) -> bytes:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}",
        headers={"xi-api-key": KEY, "Accept": "audio/mpeg", "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True},
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.content


def main() -> None:
    if not KEY:
        print("ERROR: ELEVENLABS_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    data = json.loads(LH.read_text())
    items = data.get("lighthouses", [])
    OUTDIR.mkdir(parents=True, exist_ok=True)
    made = failed = 0
    for l in items:
        slug, script = l.get("slug"), (l.get("script") or "").strip()
        if not slug or not script:
            continue
        out = OUTDIR / f"{slug}.mp3"
        rel = f"audio/lighthouses/{slug}.mp3"
        if out.exists() and not FORCE:
            if l.get("audio_url") != rel:
                l["audio_url"] = rel
            print(f"[audio] skip {slug} (already generated)")
            continue
        try:
            out.write_bytes(synth(script))
            l["audio_url"] = rel
            made += 1
            print(f"[audio] ✓ {slug} -> {rel}")
        except Exception as e:
            failed += 1
            print(f"[audio] ✗ {slug}: {e}", file=sys.stderr)
    LH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"[audio] done — {made} generated, {failed} failed, voice={VOICE}, model={MODEL}")
    if failed and not made:
        sys.exit(1)


if __name__ == "__main__":
    main()
