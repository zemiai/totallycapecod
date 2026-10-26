#!/usr/bin/env python3
"""Automated, fact-checked guide writer for Totally Cape Cod.

A guide goes live only if every stage passes:

 1. PICK      the next topic in content/plan.json whose season window includes today.
 2. RESEARCH  gather evidence — web search (Anthropic `web_search` tool), the topic's seed
              URLs, and Totally Cape Cod's own live data (events credited to their organizers).
              Every note kept carries verbatim evidence text + the URL it came from:
                * Anthropic: evidence = the API's own citation objects (cited_text), not
                  model-written quotes;
                * Gemini fallback: the model must quote the documents and Python checks each
                  quote is really in the fetched text.
 3. DRAFT     write the guide ONLY from those notes, citing sources as [n].
 4. CHECK     (a) build_site validation — every factual line cited, every citation real;
              (b) number/date check — each number, date and time in a cited sentence must
                  appear in that source's evidence;
              (c) independent audit — a fresh model call lists any unsupported sentence.
              One revision round. If anything still fails, the draft is parked in
              content/drafts/ with a report and nothing is published.
 5. PUBLISH   write content/articles/<slug>.md, mark the topic published, rebuild the site.

Env:
  ANTHROPIC_API_KEY  preferred (enables web research)   | GEMINI_API_KEY  fallback (seed URLs + site data)
  CONTENT_MODEL      default claude-sonnet-5-5           | GEMINI_MODEL    default gemini-2.5-pro
  CONTENT_TOPIC=<id> force a topic                       | DRY_RUN=1       stop before writing files
  CONTENT_LLM=mock   offline test mode (scripts/content/fixtures/)
Exits 0 with "[writer] skip: …" when there's nothing to do or no key, so the workflow stays green.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content"
PLAN = Path(os.environ["CONTENT_PLAN"]) if os.environ.get("CONTENT_PLAN") else CONTENT / "plan.json"
DRAFTS = CONTENT / "drafts"
DATA = Path(os.environ["CONTENT_DATA_DIR"]) if os.environ.get("CONTENT_DATA_DIR") else ROOT / "data"
ET = ZoneInfo("America/New_York")
TODAY = datetime.now(ET).date()
UA = {"User-Agent": "TotallyCapeCodBot/1.0 (+https://totallycapecod.com/guides/standards/)"}

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MOCK = os.environ.get("CONTENT_LLM", "") == "mock"
MODEL = os.environ.get("CONTENT_MODEL", "").strip() or "claude-sonnet-5-5"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-pro"
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"

PUBLISHERS = {
    "nps.gov": "National Park Service", "noaa.gov": "NOAA", "fisheries.noaa.gov": "NOAA Fisheries",
    "weather.gov": "National Weather Service", "mass.gov": "Commonwealth of Massachusetts",
    "fws.gov": "U.S. Fish & Wildlife Service", "capecodchamber.org": "Cape Cod Chamber of Commerce",
    "facebook.com": "Facebook (organizer's public listing)", "capecodcommission.org": "Cape Cod Commission",
    "barnstablecounty.org": "Barnstable County", "capecod.gov": "Barnstable County",
}

STYLE_RULES = """
House rules (non-negotiable — a real person's name is on every guide):
- Use ONLY facts from the research notes. Never add a date, time, price, address, count, rule, season,
  quote, ranking or description that is not in the notes. If something useful isn't in the notes, leave it out.
- Every sentence that states a fact ends with its citation(s) like [2] or [1, 4], using the SOURCE numbers given.
- Keep dates exactly as the notes give them, with the year where the notes give one. If a note says a schedule is
  tentative, or dates are from a past year, say so plainly.
- No first-person anecdotes or invented experiences ("I went…", "my favorite…"). Use "we" only for Totally Cape Cod.
- No superlatives or rankings ("best", "most popular", "#1") unless a cited source says exactly that.
- Credit organizers by name. Prefer "according to <organizer>" for anything that could change.
- Plain, helpful, local tone. Short paragraphs. Use ## headings. Bullet lists for schedules.
- Advice that contains no facts (e.g. "confirm before you drive") needs no citation and must not contain numbers or dates.
- You may link to these Totally Cape Cod pages where relevant (no citation needed): /events.html (live events),
  /cape-cod-bridge-traffic.html (live bridge delays), /cape-cod-water-temperature-today.html (water temps),
  /cape-cod-beach-conditions-today.html, /app/ (free app), /guides/ (more guides).
- For event-heavy topics you may add a live events list with this exact shortcode on its own line:
  {{events match="regex of keywords" from="YYYY-MM-DD" to="YYYY-MM-DD" limit="30" group="day"}}
"""


def log(msg: str) -> None:
    print(f"[writer] {msg}", flush=True)


# ------------------------------------------------------------------ helpers --
def norm_text(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def publisher_for(url: str, title: str = "") -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for dom, name in PUBLISHERS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return host


def parse_json(text: str):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"[\[{].*[\]}]", t, re.S)
    return json.loads(m.group(0) if m else t)


def fetch_text(url: str, limit: int = 40000) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
    except Exception as e:
        log(f"seed fetch failed {url}: {e}")
        return ""
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype:
        return ""   # PDFs: rely on web search citations instead
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))
    return text[:limit]


# ---------------------------------------------------------------------- LLM --
class LLM:
    def __init__(self):
        if MOCK:
            self.kind = "mock"
        elif ANTHROPIC_KEY:
            self.kind = "anthropic"
        elif GEMINI_KEY:
            self.kind = "gemini"
        else:
            self.kind = None
        self.fixtures = {}
        if MOCK:
            fx = Path(__file__).resolve().parent / "fixtures" / os.environ.get("CONTENT_MOCK", "mock_ok.json")
            self.fixtures = json.loads(fx.read_text(encoding="utf-8"))
            self.calls = {}

    def _mock(self, stage: str):
        n = self.calls.get(stage, 0)
        self.calls[stage] = n + 1
        seq = self.fixtures[stage]
        return seq[min(n, len(seq) - 1)]

    def anthropic(self, payload: dict) -> dict:
        for attempt in range(4):
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=300, json=payload,
                              headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"})
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(15 * (attempt + 1))
                continue
            if not r.ok:
                raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:500]}")
            return r.json()
        raise RuntimeError("Anthropic API kept failing (rate limit/overload)")

    def chat(self, system: str, user: str, stage: str, max_tokens: int = 8000) -> str:
        """Plain text-in/text-out call used for drafting, revising and auditing."""
        if self.kind == "mock":
            return self._mock(stage)
        if self.kind == "anthropic":
            data = self.anthropic({"model": MODEL, "max_tokens": max_tokens, "temperature": 0.2 if stage != "audit" else 0,
                                   "system": system, "messages": [{"role": "user", "content": user}]})
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        r = requests.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", timeout=300,
                          headers={"Authorization": f"Bearer {GEMINI_KEY}"},
                          json={"model": GEMINI_MODEL, "temperature": 0.2,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if not r.ok:
            raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:500]}")
        return r.json()["choices"][0]["message"]["content"]


# ------------------------------------------------------------------- topic ---
def in_window(topic: dict, today: date) -> bool:
    w = topic.get("window")
    if not w:
        return True
    md = today.month * 100 + today.day
    a = int(w["from"].replace("-", "")); b = int(w["to"].replace("-", ""))
    return a <= md <= b if a <= b else (md >= a or md <= b)   # windows may wrap the new year


def pick_topic(plan: dict) -> dict | None:
    forced = os.environ.get("CONTENT_TOPIC", "").strip()
    topics = plan.get("topics", [])
    if forced:
        return next((t for t in topics if t["id"] == forced), None)
    due = [t for t in topics if t.get("status", "queued") == "queued" and t.get("auto", True) and in_window(t, TODAY)]
    due.sort(key=lambda t: (t.get("priority", 50), t["id"]))
    return due[0] if due else None


# ---------------------------------------------------------------- research ---
def site_data_docs(topic: dict) -> list[dict]:
    """Totally Cape Cod's own data, one document per item so citations map to the organizer."""
    docs = []
    wants = set(topic.get("data", []))
    if "events" in wants:
        frm = topic.get("events_from") or TODAY.isoformat()
        to = topic.get("events_to") or ""
        rx = re.compile(topic["events_match"], re.I) if topic.get("events_match") else None
        seen = set()
        for fname in ("curated.json", "events.json"):
            try:
                evs = json.loads((DATA / fname).read_text(encoding="utf-8")).get("events", [])
            except Exception:
                evs = []
            for e in evs:
                day = (e.get("start") or "")[:10]
                if not day or day < frm or (to and day > to) or not e.get("source_url"):
                    continue
                if rx and not rx.search(" ".join(str(e.get(k, "")) for k in ("title", "tag", "venue", "info"))):
                    continue
                key = (e.get("title", "").lower(), day)
                if key in seen:
                    continue
                seen.add(key)
                credit = e.get("credit") or e.get("source") or publisher_for(e["source_url"])
                body = (f"Event: {e.get('title')}\nDate: {day}\nWhen: {e.get('time', '')}\nWhere: "
                        f"{', '.join(x for x in (e.get('venue'), e.get('town')) if x)}\nOrganizer/listing: {credit}\n"
                        f"Price: {e.get('price') or 'not listed'}\nDetails: {e.get('info') or ''}")
                docs.append({"title": f"{e.get('title')} — {credit}", "url": e["source_url"], "publisher": credit,
                             "text": body, "kind": "data"})
    return docs[:40]


def research_anthropic(llm: LLM, topic: dict, seed_docs: list[dict]) -> list[dict]:
    """Web search + seed/data documents with the Citations API. Evidence = API citation objects."""
    content = []
    for d in seed_docs:
        content.append({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": d["text"]},
                        "title": d["title"][:250], "context": d["url"], "citations": {"enabled": True}})
    content.append({"type": "text", "text": f"""Today is {TODAY.isoformat()}. You are researching facts for a Cape Cod travel guide.

Guide: {topic['title']}
Target searches: {', '.join(topic.get('keywords', []))}
Brief: {topic.get('brief', '')}

Use web search (and the attached documents) to find current, specific facts. Prefer official sources: the event or
business organizer's own site or listing, town/state/federal agencies (NPS, NOAA, mass.gov), chambers of commerce.
Avoid content farms. Then write RESEARCH NOTES as short separate statements, each directly supported by a citation:
dates (with year), times, places/addresses, organizers, rules, seasons, prices, counts. Say when a source is old or
a schedule is tentative. No opinions, no inferences, nothing you can't cite."""})
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": int(os.environ.get("CONTENT_MAX_SEARCHES", "8")),
              "user_location": {"type": "approximate", "city": "Hyannis", "region": "Massachusetts", "country": "US",
                                "timezone": "America/New_York"}}]
    messages = [{"role": "user", "content": content}]
    blocks = []
    for _ in range(4):  # handle pause_turn continuations
        data = llm.anthropic({"model": MODEL, "max_tokens": 8000, "messages": messages, "tools": tools})
        blocks += data.get("content", [])
        if data.get("stop_reason") != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": data["content"]}]
    notes = []
    for b in blocks:
        if b.get("type") != "text" or not b.get("citations"):
            continue
        ev = []
        for c in b["citations"]:
            if c.get("type") == "web_search_result_location":
                ev.append({"url": c.get("url"), "title": c.get("title") or "", "text": c.get("cited_text") or ""})
            elif c.get("type") in ("char_location", "content_block_location", "page_location"):
                d = seed_docs[c.get("document_index", 0)] if c.get("document_index", 0) < len(seed_docs) else None
                if d:
                    ev.append({"url": d["url"], "title": d["title"], "text": c.get("cited_text") or "", "publisher": d.get("publisher")})
        ev = [e for e in ev if e["url"] and e["text"].strip()]
        if ev:
            notes.append({"note": b["text"].strip(), "evidence": ev})
    return notes


def research_quotes(llm: LLM, topic: dict, seed_docs: list[dict]) -> list[dict]:
    """Fallback (Gemini/mock): model quotes the documents; Python keeps only quotes found verbatim."""
    if not seed_docs:
        return []
    listing = "\n\n".join(f"[D{i + 1}] {d['title']} ({d['url']})\n{d['text'][:12000]}" for i, d in enumerate(seed_docs))
    raw = llm.chat("You extract facts from documents for a travel guide. Output JSON only.",
                   f"""Today is {TODAY.isoformat()}. Guide: {topic['title']}. Brief: {topic.get('brief', '')}

Documents:
{listing}

Return a JSON array of facts useful for the guide: [{{"note": "short factual statement", "doc": "D3",
"quote": "exact text copied character-for-character from that document that proves the note"}}].
Only include facts with an exact supporting quote (max 300 characters). Include dates with years where given.""",
                   stage="research")
    try:
        items = parse_json(raw)
    except Exception:
        log("research: could not parse JSON")
        return []
    notes = []
    for it in items if isinstance(items, list) else []:
        m = re.match(r"D(\d+)", str(it.get("doc", "")))
        if not m or not it.get("quote") or not it.get("note"):
            continue
        i = int(m.group(1)) - 1
        if not (0 <= i < len(seed_docs)):
            continue
        d = seed_docs[i]
        if norm_text(it["quote"]) in norm_text(d["text"]):
            notes.append({"note": it["note"].strip(), "evidence": [{"url": d["url"], "title": d["title"],
                                                                     "text": it["quote"], "publisher": d.get("publisher")}]})
        else:
            log(f"research: dropped unverifiable quote from {d['url']}: {it['quote'][:80]!r}")
    return notes


# ------------------------------------------------------------- sources/notes --
def number_sources(notes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Unique source per URL, numbered 1..n; each note gets the source ids its evidence came from."""
    sources, by_url = [], {}
    for n in notes:
        ids = []
        for e in n["evidence"]:
            u = e["url"].split("#")[0]
            if u not in by_url:
                by_url[u] = len(sources) + 1
                sources.append({"id": by_url[u], "url": u, "title": (e.get("title") or u)[:200],
                                "publisher": e.get("publisher") or publisher_for(u), "accessed": TODAY.isoformat()})
            ids.append(by_url[u])
        n["sources"] = sorted(set(ids))
    return sources, notes


def notes_prompt(sources: list[dict], notes: list[dict]) -> str:
    src = "\n".join(f"[{s['id']}] {s['publisher']} — {s['title']} — {s['url']}" for s in sources)
    nts = "\n".join(f"- {n['note']}  (sources: {', '.join(map(str, n['sources']))}; evidence: "
                    + " | ".join(json.dumps(e['text'][:300]) for e in n['evidence']) + ")" for n in notes)
    return f"SOURCES:\n{src}\n\nRESEARCH NOTES (the only facts you may use):\n{nts}"


# ------------------------------------------------------------------- draft ---
DRAFT_FORMAT = """Return JSON only:
{"title": "...", "seo_title": "... (<= 60 chars)", "kicker": "short label", "description": "meta description, <= 155 chars, no citations",
 "faq": [{"q": "a question people search", "a": "answer with citations [n]"}],
 "body_markdown": "the guide body in Markdown with ## headings and [n] citations"}
Write 700-1400 words. 3-5 FAQ items, each answer cited."""


def draft(llm: LLM, topic: dict, sources: list[dict], notes: list[dict]) -> dict:
    raw = llm.chat("You write accurate, source-cited Cape Cod guides for Totally Cape Cod. " + STYLE_RULES,
                   f"""Write the guide "{topic['title']}" (today is {TODAY.isoformat()}).
Target searches: {', '.join(topic.get('keywords', []))}
Brief: {topic.get('brief', '')}

{notes_prompt(sources, notes)}

{DRAFT_FORMAT}""", stage="draft")
    return parse_json(raw)


def revise(llm: LLM, topic: dict, sources: list[dict], notes: list[dict], doc: dict, problems: list[str]) -> dict:
    raw = llm.chat("You correct source-cited Cape Cod guides. " + STYLE_RULES,
                   f"""This draft failed fact-checking. Fix every problem: correct the sentence to match the evidence,
or delete it. Do not add new facts.

PROBLEMS:
{chr(10).join('- ' + p for p in problems)}

{notes_prompt(sources, notes)}

DRAFT JSON:
{json.dumps(doc, ensure_ascii=False)}

{DRAFT_FORMAT}""", stage="revise")
    return parse_json(raw)


# ------------------------------------------------------------------- check ---
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def fact_tokens(s: str) -> set[str]:
    """Normalized numbers, years, times and month-day pairs in a string."""
    t = norm_text(CITE_STRIP.sub("", s))
    t = re.sub(r"\]\([^)]*\)", "]", t)                                   # drop markdown link targets
    toks = set()
    for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t):            # ISO dates in data docs
        toks.update({f"md:{int(m.group(2))}-{int(m.group(3))}", f"n:{m.group(1)}"})
    t = re.sub(r"\b20\d{2}-\d{2}-\d{2}(t[\d:+\-.]*)?\b", " ", t)
    for m in re.finditer(MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        toks.add(f"md:{MONTHS[m.group(1)[:3]]}-{int(m.group(2))}")
    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s?(a\.?m\.?|p\.?m\.?)", t):
        toks.add(f"tm:{int(m.group(1))}:{m.group(2) or '00'}{m.group(3)[0]}")
    t2 = re.sub(MONTH_RE + r"\s+\d{1,2}(?:st|nd|rd|th)?\b", " ", t)
    t2 = re.sub(r"\b\d{1,2}(?::\d{2})?\s?(a\.?m\.?|p\.?m\.?)", " ", t2)
    for m in re.finditer(r"\b(\d+)(?:st|nd|rd|th)\b", t2):            # ordinals: 63rd → 63
        toks.add("n:" + m.group(1))
    t2 = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", t2)
    for m in re.finditer(r"\$?\b\d[\d,]*(?:\.\d+)?\b", t2):
        toks.add("n:" + m.group(0).replace(",", "").lstrip("$"))
    return toks


CITE_STRIP = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()")


def check_numbers(doc: dict, sources: list[dict], notes: list[dict]) -> list[str]:
    ev_by_src: dict[int, str] = {}
    for n in notes:
        for e in n["evidence"]:
            for s in sources:
                if s["url"] == e["url"].split("#")[0]:
                    ev_by_src[s["id"]] = ev_by_src.get(s["id"], "") + " " + e["text"]
    problems = []
    texts = [doc.get("body_markdown", "")] + [f["a"] for f in doc.get("faq", [])]
    for text in texts:
        for line in text.splitlines():
            if line.strip().startswith(("#", "{{", "|---")):
                continue
            for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z*])", line):
                ids = {int(x) for m in CITE_STRIP.finditer(sent) for x in m.group(1).split(",")}
                if not ids:
                    continue
                need = fact_tokens(sent)
                have = set()
                for i in ids:
                    have |= fact_tokens(ev_by_src.get(i, ""))
                # a bare day number in a range ("Nov 27–29") is fine if the evidence has that day as a date
                missing = {t for t in need - have
                           if not (t.startswith("n:") and any(h.startswith("md:") and h.split("-")[1] == t[2:] for h in have))}
                if missing:
                    problems.append(f"Numbers/dates not found in cited evidence {sorted(missing)}: {sent.strip()[:220]}")
    return problems


def audit(llm: LLM, sources: list[dict], notes: list[dict], doc: dict) -> list[str]:
    raw = llm.chat("You are a strict fact-checker. Output JSON only.",
                   f"""Check this guide against the research notes and evidence. List EVERY sentence (body or FAQ) that:
states something not supported by its cited evidence; cites the wrong source; overstates (e.g. presents a tentative
or past-year date as confirmed); invents an experience, ranking or superlative; or states a fact with no citation.

{notes_prompt(sources, notes)}

GUIDE JSON:
{json.dumps(doc, ensure_ascii=False)}

Return {{"issues": [{{"sentence": "...", "problem": "..."}}]}} — an empty list if everything is supported.""",
                   stage="audit", max_tokens=4000)
    try:
        data = parse_json(raw)
        return [f"{i.get('problem')}: {i.get('sentence', '')[:220]}" for i in data.get("issues", [])]
    except Exception:
        return ["Audit response could not be parsed — treating as failed"]


def to_markdown(topic: dict, doc: dict, sources: list[dict]) -> str:
    used = {int(x) for t in [doc.get("body_markdown", "")] + [f["a"] for f in doc.get("faq", [])]
            for m in CITE_STRIP.finditer(t) for x in m.group(1).split(",")}
    srcs = [s for s in sources if s["id"] in used]
    meta = {
        "title": doc["title"].strip(), "seo_title": (doc.get("seo_title") or doc["title"]).strip(),
        "slug": topic["slug"], "kicker": doc.get("kicker") or topic.get("kicker") or "Guide",
        "description": doc["description"].strip()[:160], "date": TODAY.isoformat(), "updated": TODAY.isoformat(),
        "author": topic.get("author", "versel-johnson"), "cluster": topic.get("cluster", ""),
        "keywords": topic.get("keywords", []), "faq": doc.get("faq", []), "sources": srcs,
        "generated_by": f"content-writer ({'mock' if MOCK else (MODEL if ANTHROPIC_KEY else GEMINI_MODEL)})",
    }
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000) + "---\n\n" + doc["body_markdown"].strip() + "\n"


def full_check(llm: LLM, topic: dict, doc: dict, sources: list[dict], notes: list[dict]) -> list[str]:
    problems = []
    for k in ("title", "description", "body_markdown"):
        if not doc.get(k):
            problems.append(f"draft missing {k}")
    if problems:
        return problems
    md = to_markdown(topic, doc, sources)
    meta, body = build_site.parse_article_text(md)
    problems += build_site.validate(meta, body, build_site.load_authors())
    problems += check_numbers(doc, sources, notes)
    if not problems:
        problems += audit(llm, sources, notes, doc)
    return problems


# -------------------------------------------------------------------- main ---
def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    topic = pick_topic(plan)
    if not topic:
        log("skip: no queued topic is in season today")
        return 0
    llm = LLM()
    if not llm.kind:
        log(f"skip: no ANTHROPIC_API_KEY or GEMINI_API_KEY secret — next topic would be '{topic['id']}'")
        return 0
    log(f"topic: {topic['id']} — {topic['title']} ({llm.kind})")

    seed_docs = []
    for u in topic.get("seed_urls", []):
        txt = fetch_text(u)
        if txt.strip():
            seed_docs.append({"title": u, "url": u, "text": txt, "kind": "seed", "publisher": publisher_for(u)})
    seed_docs += site_data_docs(topic)
    notes = research_anthropic(llm, topic, seed_docs) if llm.kind == "anthropic" else research_quotes(llm, topic, seed_docs)
    min_notes = int(topic.get("min_notes", 8))
    log(f"research: {len(notes)} verified notes from {len(seed_docs)} documents")
    if len(notes) < min_notes:
        log(f"skip: only {len(notes)} verified facts (need {min_notes}) — not enough to write a trustworthy guide")
        return 0
    sources, notes = number_sources(notes)

    doc = draft(llm, topic, sources, notes)
    problems = full_check(llm, topic, doc, sources, notes)
    if problems:
        log(f"check: {len(problems)} problem(s) — revising once")
        doc = revise(llm, topic, sources, notes, doc, problems)
        problems = full_check(llm, topic, doc, sources, notes)

    md = to_markdown(topic, doc, sources) if doc.get("body_markdown") else ""
    if problems:
        DRAFTS.mkdir(parents=True, exist_ok=True)
        if not DRY_RUN:
            (DRAFTS / f"{topic['slug']}.md").write_text(md or json.dumps(doc, indent=2), encoding="utf-8")
            (DRAFTS / f"{topic['slug']}.report.txt").write_text("\n".join(problems), encoding="utf-8")
            topic["status"] = "needs_review"
            topic["last_attempt"] = TODAY.isoformat()
            PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (ROOT / ".content_commit_msg").write_text(f"parked draft for review: {topic['id']} ({len(problems)} fact-check issues)")
        log("NOT PUBLISHED — fact-check failed:\n  " + "\n  ".join(problems))
        return 0
    if DRY_RUN:
        log("dry run: passed all checks; not writing files\n" + md[:3000])
        return 0
    (CONTENT / "articles" / f"{topic['slug']}.md").write_text(md, encoding="utf-8")
    topic["status"] = "published"
    topic["published"] = TODAY.isoformat()
    PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rc = build_site.main_build()
    if rc != 0:
        log("build failed after writing — removing article")
        (CONTENT / "articles" / f"{topic['slug']}.md").unlink(missing_ok=True)
        return 1
    (ROOT / ".content_commit_msg").write_text(f"new guide: {doc['title']} (fact-checked, {len(sources)} sources)")
    log(f"published /guides/{topic['slug']}/ with {len(sources)} sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
