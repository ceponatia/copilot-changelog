#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict

import feedparser  # type: ignore[import-untyped]
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

FEED_URL = "https://github.blog/changelog/feed/"
STATE_FILE = "seen.json"
MAX_ITEMS_PER_RUN = 5

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GITHUB_MODELS_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-5-mini")
GITHUB_MODELS_API_URL = os.environ.get(
    "GITHUB_MODELS_API_URL", "https://api.githubcopilot.com/v1/chat/completions"
)
SUMMARY_TIMEOUT = float(os.environ.get("SUMMARY_HTTP_TIMEOUT", "20"))


class EntryDict(TypedDict, total=False):
    id: str
    title: str
    link: str
    summary: str
    tags: list[dict[str, Any]]
    category: str
    published: str
    published_parsed: Any


@dataclass
class Embed:
    title: str
    url: str
    description: str
    timestamp: str


def load_state(path: str = STATE_FILE) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(str(x) for x in data)
        return set()
    except FileNotFoundError:
        return set()
    except json.JSONDecodeError:
        # Corrupt state; start fresh but don't crash
        return set()


def save_state(ids: Iterable[str], path: str = STATE_FILE) -> None:
    existing = load_state(path)
    merged = list(existing.union(set(ids)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(merged), f, indent=2)


def fetch_feed(url: str = FEED_URL) -> Any:
    return feedparser.parse(url)


def is_copilot_tagged(entry: EntryDict) -> bool:
    """Return True if entry tags/categories indicate Copilot.

    Checks tags (term or label) and category fields, case-insensitive.
    """
    needles = {"copilot", "github copilot"}

    # tags may be list of dicts with 'term' or 'label' fields
    tags = entry.get("tags") or []
    for t in tags:
        for key in ("term", "label"):
            val = str(t.get(key, ""))
            if val and val.lower() in needles:
                return True
            if "copilot" in val.lower():
                return True

    # Some feeds include 'category' as a single string
    cat = entry.get("category")
    if isinstance(cat, str) and "copilot" in cat.lower():
        return True

    # Title fallback if tags missing (rare, but safe)
    title = entry.get("title") or ""
    if isinstance(title, str) and "copilot" in title.lower():
        return True

    return False


def strip_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ")


def basic_summary(entry: EntryDict, max_len: int = 420) -> str:
    raw = entry.get("summary") or ""
    clean = strip_html(str(raw)).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def build_summary_prompt(entry: EntryDict) -> str:
    content = strip_html(str(entry.get("summary") or ""))
    title = entry.get("title") or ""
    return (
        "Summarize the following GitHub Changelog item about GitHub Copilot into 2-4 concise "
        "bullet points suitable for a Discord embed. Be factual and brief.\n\n"
        f"Title: {title}\n\n"
        f"Content: {content}\n\n"
        "Respond with only the bullets, each starting with '- '."
    )


def openai_llm_bulleted_summary(entry: EntryDict, api_key: str | None) -> str | None:
    if not api_key:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "openai/gpt-5-mini",
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "You are a concise release note summarizer."},
                {"role": "user", "content": build_summary_prompt(entry)},
            ],
        }
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=SUMMARY_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {}).get("content")
        if not isinstance(msg, str) or not msg.strip():
            return None
        lines = [ln.strip() for ln in msg.strip().splitlines() if ln.strip()]
        if not lines:
            return None
        if len(lines) > 4:
            lines = lines[:4]
        return "\n".join(lines)
    except Exception:
        return None


def github_llm_bulleted_summary(entry: EntryDict, token: str | None) -> str | None:
    if not token:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2024-07-01",
        }
        body = {
            "model": GITHUB_MODELS_MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "You are a concise release note summarizer."},
                {"role": "user", "content": build_summary_prompt(entry)},
            ],
        }
        resp = requests.post(
            GITHUB_MODELS_API_URL,
            headers=headers,
            json=body,
            timeout=SUMMARY_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {}).get("content")
        if not isinstance(msg, str) or not msg.strip():
            return None
        lines = [ln.strip() for ln in msg.strip().splitlines() if ln.strip()]
        if not lines:
            return None
        if len(lines) > 4:
            lines = lines[:4]
        return "\n".join(lines)
    except Exception:
        return None


def summarize_entry(entry: EntryDict) -> str:
    summary = github_llm_bulleted_summary(entry, GITHUB_MODELS_TOKEN)
    if summary:
        return summary
    summary = openai_llm_bulleted_summary(entry, OPENAI_API_KEY)
    if summary:
        return summary
    return basic_summary(entry)


def entry_datetime_utc(entry: EntryDict) -> datetime:
    # Prefer published, else now
    ts: datetime | None = None
    if entry.get("published"):
        try:
            ts = dateparser.parse(str(entry["published"]))
        except Exception:
            ts = None
    if ts is None and entry.get("published_parsed") is not None:
        try:
            # feedparser can give time.struct_time
            ts = datetime(*entry["published_parsed"][:6])
        except Exception:
            ts = None
    if ts is None:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def to_discord_embed(entry: EntryDict, use_ai: bool = True) -> Embed:
    title = str(entry.get("title", "GitHub Changelog"))
    url = str(entry.get("link", "https://github.blog/changelog/"))
    if use_ai:
        description = summarize_entry(entry)
    else:
        description = basic_summary(entry)

    dt = entry_datetime_utc(entry)
    ts = dt.isoformat()
    return Embed(title=title, url=url, description=description, timestamp=ts)


def post_to_discord(embeds: Sequence[Embed]) -> bool:
    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL env var", file=sys.stderr)
        return False
    if not embeds:
        return True

    payload = {
        "content": None,
        "embeds": [
            {
                "title": e.title,
                "url": e.url,
                "description": e.description,
                "timestamp": e.timestamp,
                "footer": {
                    "text": f"GitHub Copilot Changelog • {datetime.fromisoformat(e.timestamp).strftime('%Y-%m-%d %H:%M UTC')}"
                },
            }
            for e in embeds
        ],
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
        if 200 <= r.status_code < 300:
            return True
        print(f"Discord webhook error: {r.status_code} {r.text}", file=sys.stderr)
        return False
    except requests.RequestException as exc:
        print(f"Discord webhook exception: {exc}", file=sys.stderr)
        return False


def main() -> int:
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL is required.", file=sys.stderr)
        return 1

    feed = fetch_feed(FEED_URL)
    entries: list[EntryDict] = [EntryDict(**e) for e in feed.get("entries", [])]
    if not entries:
        # Nothing to do
        return 0

    seen = load_state(STATE_FILE)

    # Filter copilot-tagged and unseen
    filtered: list[EntryDict] = []
    for e in entries:
        if not is_copilot_tagged(e):
            continue
        eid = str(e.get("id") or e.get("link") or e.get("title") or "")
        if not eid:
            continue
        if eid in seen:
            continue
        filtered.append(e)

    if not filtered:
        return 0

    # Oldest -> newest for reading order
    filtered.sort(key=lambda x: entry_datetime_utc(x))

    # Safety cap
    to_send = filtered[:MAX_ITEMS_PER_RUN]

    embeds = [to_discord_embed(e) for e in to_send]
    ok = post_to_discord(embeds)
    if ok:
        ids = [str(e.get("id") or e.get("link") or e.get("title")) for e in to_send]
        save_state(ids, STATE_FILE)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
