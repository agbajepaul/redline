"""
Redline daily digest builder.

Pulls RSS/Atom feeds, keeps items about connected/autonomous vehicle security,
scores them 1-10 for "heat", writes docs/data/stories.json.

With ANTHROPIC_API_KEY set: Claude filters, scores, summarizes and suggests
research angles. Without it: a free keyword-based scorer is used instead.
"""
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "scripts" / "feeds.txt"
OUT_FILE = ROOT / "docs" / "data" / "stories.json"

KEEP_DAYS = int(os.environ.get("REDLINE_KEEP_DAYS", "365"))
LOOKBACK_DAYS = int(os.environ.get("REDLINE_LOOKBACK_DAYS", "3"))
MAX_CANDIDATES = int(os.environ.get("REDLINE_MAX_CANDIDATES", "40"))
MODEL = os.environ.get("REDLINE_MODEL", "claude-haiku-5-5")

VEHICLE_TERMS = [
    "vehicle", "automotive", "car ", "cars ", "auto ", "automaker", "oem", "tesla", "waymo",
    "robotaxi", "autonomous", "self-driving", "driverless", "adas", "lidar", "can bus",
    "ecu", "telematics", "infotainment", "head unit", "keyless", "key fob", "ev charger",
    "charging station", "ocpp", "v2x", "v2v", "dealership", "dealer", "obd", "uds",
    "iso 21434", "r155", "r156", "connected car", "connected vehicle", "pwn2own automotive",
    "aaos", "android automotive", "qnx", "autosar", "e-scooter", "fleet",
]
SECURITY_TERMS = [
    "vulnerab", "exploit", "hack", "cve-", "attack", "breach", "ransomware", "malware",
    "spoof", "jamming", "backdoor", "zero-day", "0-day", "rce", "bypass", "leak",
    "security", "cyber", "privacy", "botnet", "relay attack", "replay",
]
HOT_TERMS = {
    "remote code execution": 3, "rce": 2, "zero-day": 3, "0-day": 3, "exploited": 2,
    "in the wild": 3, "unlock": 2, "start the engine": 3, "steering": 3, "brak": 3,
    "fleet": 1, "millions": 2, "cve-": 1, "pwn2own": 2, "usenix": 2, "black hat": 2,
    "def con": 2, "defcon": 2, "rogue base station": 3, "ota": 1, "firmware": 1,
    "ransomware": 1, "lidar": 2, "spoof": 2, "can bus": 2, "telematics": 1,
}
CATEGORIES = [
    "Cellular & radio", "EV charging", "AV perception & AI", "Infotainment",
    "Telematics & privacy", "Supply chain & dealers", "Keyless & access",
    "In-vehicle networks", "Policy & regulation", "Threat reports", "Research resources",
]


def log(*a):
    print(*a, file=sys.stderr)


def clean(text, limit=600):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def story_id(url, title):
    return hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:12]


def entry_date(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def read_feeds():
    feeds = []
    for line in FEEDS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, url = line.partition("|")
            feeds.append((name.strip(), url.strip()) if url else (line, line))
    return feeds


_PAT = {}


def has(text, term):
    """Whole-word-ish match: short terms need boundaries on both sides, longer ones at the start."""
    term = term.strip().lower()
    pat = _PAT.get(term)
    if pat is None:
        tail = r"(?![a-z0-9])" if len(term) <= 4 else ""
        pat = _PAT[term] = re.compile(r"(?<![a-z0-9])" + re.escape(term) + tail)
    return bool(pat.search(text))


def is_relevant(text, vehicle_only_feed):
    t = text.lower()
    has_vehicle = any(has(t, k) for k in VEHICLE_TERMS)
    has_sec = any(has(t, k) for k in SECURITY_TERMS)
    return has_vehicle and (has_sec or vehicle_only_feed)


def collect(existing_ids):
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    out, seen_titles = [], set()
    for name, url in read_feeds():
        vehicle_only = name.startswith("*")  # '*' marks feeds that are already vehicle-focused
        name = name.lstrip("*").strip()
        try:
            parsed = feedparser.parse(url, agent="RedlineDigest/1.0 (+github pages)")
        except Exception as ex:  # noqa: BLE001
            log(f"[skip] {name}: {ex}")
            continue
        if parsed.bozo and not parsed.entries:
            log(f"[skip] {name}: unreadable feed")
            continue
        n = 0
        for e in parsed.entries[:60]:
            title = clean(e.get("title"), 300)
            link = e.get("link", "")
            summary = clean(e.get("summary") or e.get("description"))
            when = entry_date(e)
            if when and when < cutoff:
                continue
            sid = story_id(link, title)
            key = re.sub(r"\W+", "", title.lower())[:80]
            if sid in existing_ids or key in seen_titles:
                continue
            if not is_relevant(f"{title} {summary}", vehicle_only):
                continue
            seen_titles.add(key)
            src = name
            if "news.google.com" in url and e.get("source", {}).get("title"):
                src = e["source"]["title"]
            out.append({
                "id": sid, "title": title, "url": link, "source": src,
                "published": (when or datetime.now(timezone.utc)).date().isoformat(),
                "raw": summary,
            })
            n += 1
        log(f"[ok] {name}: {n} candidates")
    return out[:MAX_CANDIDATES]


# ---------- Free scorer (no API key) ----------
def guess_category(t):
    t = t.lower()
    rules = [
        ("EV charging", ["charger", "charging", "ocpp", "charx"]),
        ("Cellular & radio", ["lte", "cellular", "5g", "base station", "imsi", "gnss", "gps", "v2x", "jamming"]),
        ("AV perception & AI", ["lidar", "camera", "perception", "autonomous", "self-driving", "robotaxi", "adas", "adversarial"]),
        ("Infotainment", ["infotainment", "head unit", "carplay", "android auto", "bluetooth"]),
        ("Keyless & access", ["keyless", "key fob", "relay attack", "unlock", "immobilizer"]),
        ("In-vehicle networks", ["can bus", "ecu", "autosar", "uds", "ethernet"]),
        ("Supply chain & dealers", ["dealer", "supplier", "tier-1", "tier 1", "cdk"]),
        ("Policy & regulation", ["rule", "regulat", "nhtsa", "r155", "commerce", "law", "bill"]),
        ("Threat reports", ["report", "q1", "q2", "q3", "q4", "annual"]),
        ("Telematics & privacy", ["telematics", "privacy", "data", "api", "app"]),
    ]
    for cat, keys in rules:
        if any(has(t, k) for k in keys):
            return cat
    return "Threat reports"


def heuristic(cands):
    stories = []
    for c in cands:
        t = (c["title"] + " " + c["raw"]).lower()
        score = 3 + sum(w for k, w in HOT_TERMS.items() if has(t, k))
        stories.append({
            **{k: c[k] for k in ("id", "title", "url", "source", "published")},
            "category": guess_category(t),
            "heat": max(1, min(10, score)),
            "summary": c["raw"][:400] or "Open the article for details.",
            "whyItMatters": "",
            "researchAngle": "",
        })
    return stories, ""


# ---------- Claude scorer ----------
PROMPT = """You curate a daily vehicle cybersecurity digest for a security researcher who wants the juicy, technically meaty stories that could lead to research ideas.

Below are candidate items (JSON). For each one that is genuinely about the security or privacy of connected vehicles, autonomous vehicles, EV charging, vehicle-adjacent infrastructure (dealers, telematics backends, fleets), or regulation of these, return an object. Drop off-topic items, marketing fluff and duplicates.

Fields:
- "id": copy from input
- "category": one of {cats}
- "heat": integer 1-10. 9-10 = novel remote/physical-impact attack on real vehicles or in-the-wild exploitation; 7-8 = significant new vulns, strong research, notable incidents; 4-6 = reports, policy, patches; 1-3 = minor.
- "summary": 2-3 plain sentences in your own words.
- "whyItMatters": 1 sentence on why a researcher should care.
- "researchAngle": 1-2 sentences proposing an ethical, legally scoped research direction (lab rigs, owned hardware, simulators, public data, coordinated disclosure).

Also return a "briefing": 2-3 sentences summarizing today's most important threads.

Reply with ONLY JSON: {{"briefing": "...", "stories": [ ... ]}}

Candidates:
{items}
"""


def with_claude(cands):
    import anthropic

    client = anthropic.Anthropic()
    items = [{"id": c["id"], "title": c["title"], "source": c["source"], "date": c["published"], "snippet": c["raw"]} for c in cands]
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": PROMPT.format(cats=json.dumps(CATEGORIES), items=json.dumps(items, ensure_ascii=False))}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    by_id = {c["id"]: c for c in cands}
    stories = []
    for s in data.get("stories", []):
        c = by_id.get(s.get("id"))
        if not c:
            continue
        stories.append({
            "id": c["id"], "title": c["title"], "url": c["url"], "source": c["source"],
            "published": c["published"],
            "category": s.get("category") if s.get("category") in CATEGORIES else guess_category(c["title"]),
            "heat": max(1, min(10, int(s.get("heat", 5)))),
            "summary": s.get("summary", ""),
            "whyItMatters": s.get("whyItMatters", ""),
            "researchAngle": s.get("researchAngle", ""),
        })
    return stories, data.get("briefing", "")


def main():
    old = {"briefing": "", "lastUpdated": "", "stories": []}
    if OUT_FILE.exists():
        try:
            old = json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            log("[warn] stories.json unreadable, starting fresh")
    existing = {s["id"]: s for s in old.get("stories", [])}
    seen = list(old.get("seen", []))  # ids already reviewed, including ones Claude dropped

    cands = collect(set(existing) | set(seen))
    log(f"{len(cands)} new candidates")

    new, briefing = [], old.get("briefing", "")
    if cands:
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                new, b = with_claude(cands)
                briefing = b or briefing
            except Exception as ex:  # noqa: BLE001
                log(f"[warn] Claude scoring failed ({ex}); using keyword scorer")
                new, _ = heuristic(cands)
        else:
            new, _ = heuristic(cands)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
    merged = {**existing, **{s["id"]: s for s in new}}
    stories = sorted(
        (s for s in merged.values() if s.get("published", "") >= cutoff),
        key=lambda s: (s.get("published", ""), s.get("heat", 0)), reverse=True,
    )
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "lastUpdated": datetime.now(timezone.utc).date().isoformat(),
        "briefing": briefing,
        "stories": stories,
        "seen": (seen + [c["id"] for c in cands])[-3000:],
    }, indent=1, ensure_ascii=False))
    log(f"wrote {len(stories)} stories ({len(new)} new)")


if __name__ == "__main__":
    main()
