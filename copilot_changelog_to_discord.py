#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict

# feedparser will show up as 'could not be resolved' in some IDEs unless you have the venv set as your interpreter
import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

FEED_URL = "https://github.blog/changelog/feed/"
STATE_FILE = "seen.json"
MAX_ITEMS_PER_RUN = 5

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_THREAD_ID = os.environ.get("DISCORD_THREAD_ID")
DISCORD_THREAD_NAME = os.environ.get("DISCORD_THREAD_NAME")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GITHUB_MODELS_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-5-mini")
GITHUB_MODELS_API_URL = os.environ.get(
    "GITHUB_MODELS_API_URL", "https://api.githubcopilot.com/v1/chat/completions"
)
# Forum posting mode: per-item (default), auto, single, off
DISCORD_FORUM_MODE = os.environ.get("DISCORD_FORUM_MODE", "per-item").strip().lower()
SUMMARY_TIMEOUT = float(os.environ.get("SUMMARY_HTTP_TIMEOUT", "20"))
FORCE_POST = os.environ.get("FORCE_POST", "").strip() not in ("", "0", "false", "False")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false", "False")
SUMMARY_DEBUG = os.environ.get("SUMMARY_DEBUG", "").strip() not in ("", "0", "false", "False")


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


def entry_fingerprint(entry: EntryDict) -> str:
    """Return a stable identifier for a feed entry.

    Prefer the feed's `id`/`guid` fields, else fall back to `link` or `title`.
    """
    for key in ("id", "guid", "entry_id"):
        v = entry.get(key)
        if v:
            return str(v)
    return str(entry.get("link") or entry.get("title") or "")


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


def build_title_prompt(entry: EntryDict) -> str:
    """Prompt to derive a short forum thread title.

    Constraints:
    - 4-10 words
    - No surrounding quotes or trailing punctuation
    - Max ~90 characters
    - Should clearly identify the Copilot change
    """
    content = strip_html(str(entry.get("summary") or ""))
    title = entry.get("title") or ""
    return (
        "Create a concise forum thread title for the following GitHub Copilot changelog item.\n"
        "- 4 to 10 words\n- Avoid quotes and ending punctuation\n- Max 90 characters\n"
        "Respond with ONLY the title text.\n\n"
        f"Original Title: {title}\n\n"
        f"Content: {content}\n"
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


def _clean_title(raw: str, max_len: int = 90) -> str:
    s = strip_html(raw).strip()
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # Remove surrounding quotes
    s = s.strip('\'" ')  # handles both single and double quotes and spaces
    # Trim trailing punctuation often added by models
    s = re.sub(r"[\s\-–—:.,;!?#]+$", "", s)
    # Enforce length
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s


def openai_llm_thread_title(entry: EntryDict, api_key: str | None) -> str | None:
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
                {"role": "system", "content": "You are a helpful assistant that writes brief titles."},
                {"role": "user", "content": build_title_prompt(entry)},
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
        title = _clean_title(msg)
        return title or None
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


def github_llm_thread_title(entry: EntryDict, token: str | None) -> str | None:
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
                {"role": "system", "content": "You are a helpful assistant that writes brief titles."},
                {"role": "user", "content": build_title_prompt(entry)},
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
        title = _clean_title(msg)
        return title or None
    except Exception:
        return None


def summarize_entry(entry: EntryDict) -> str:
    summary = github_llm_bulleted_summary(entry, GITHUB_MODELS_TOKEN)
    if summary:
        if SUMMARY_DEBUG:
            print("SUMMARY_DEBUG: used GitHub Models", file=sys.stderr)
        return summary
    summary = openai_llm_bulleted_summary(entry, OPENAI_API_KEY)
    if summary:
        if SUMMARY_DEBUG:
            print("SUMMARY_DEBUG: used OpenAI fallback", file=sys.stderr)
        return summary
    if SUMMARY_DEBUG:
        print("SUMMARY_DEBUG: used basic summary", file=sys.stderr)
    return basic_summary(entry)


def derive_thread_name(entry: EntryDict) -> str:
    """Derive a Discord forum thread name for a changelog entry.

    Preference order:
    1) GitHub Models title
    2) OpenAI fallback
    3) Sanitized entry title
    4) Fallback from summary
    """
    title = github_llm_thread_title(entry, GITHUB_MODELS_TOKEN)
    if title:
        if SUMMARY_DEBUG:
            print("SUMMARY_DEBUG: title via GitHub Models", file=sys.stderr)
        return title
    title = openai_llm_thread_title(entry, OPENAI_API_KEY)
    if title:
        if SUMMARY_DEBUG:
            print("SUMMARY_DEBUG: title via OpenAI fallback", file=sys.stderr)
        return title
    # Fall back to entry title
    raw = str(entry.get("title") or "").strip()
    if raw:
        return _clean_title(raw)
    # Last resort: derive from basic summary first sentence/phrase
    bs = basic_summary(entry, max_len=90)
    # Take up to first sentence or 8 words
    first = re.split(r"[.!?]\s|\n", bs, maxsplit=1)[0]
    words = first.split()
    if len(words) > 10:
        first = " ".join(words[:10])
    return _clean_title(first or "GitHub Copilot Changelog")


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


def post_to_discord(embeds: Sequence[Embed], thread_name: str | None = None) -> tuple[bool, int | None]:
    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL env var", file=sys.stderr)
        return False, None
    if not embeds:
        return True, None

    # Append thread_id for forum channels when provided
    url = DISCORD_WEBHOOK_URL
    if DISCORD_THREAD_ID:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}thread_id={DISCORD_THREAD_ID}"

    payload: dict[str, Any] = {
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
    # For forum channels, you can create a thread on-the-fly by passing thread_name
    chosen_thread_name = thread_name or (DISCORD_THREAD_NAME or None)
    if chosen_thread_name and not DISCORD_THREAD_ID:
        payload["thread_name"] = chosen_thread_name
    if DRY_RUN:
        try:
            print(json.dumps({"url": url, **payload}, indent=2))
        except Exception:
            print("DRY_RUN: (payload not JSON-serializable)")
        print("DRY_RUN: skipping Discord webhook post", file=sys.stderr)
        return True, None
    try:
        r = requests.post(url, json=payload, timeout=20)
        if 200 <= r.status_code < 300:
            return True, None
        # Helpful hint for forum channel error code 220001
        hint = ""
        err_code: int | None = None
        try:
            err = r.json()
            if isinstance(err, dict):
                err_code = err.get("code") if isinstance(err.get("code"), int) else None
                if err_code == 220001:
                    hint = (
                        "\nHint: The webhook targets a Forum channel. Provide a thread by setting "
                        "DISCORD_THREAD_ID (existing thread) or DISCORD_THREAD_NAME (to create a thread)."
                    )
        except Exception:
            pass
        print(f"Discord webhook error: {r.status_code} {r.text}{hint}", file=sys.stderr)
        return False, err_code
    except requests.RequestException as exc:
        print(f"Discord webhook exception: {exc}", file=sys.stderr)
        return False, None


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
        eid = entry_fingerprint(e)
        if not eid:
            continue
        if not FORCE_POST and eid in seen:
            continue
        filtered.append(e)

    if not filtered:
        return 0

    # Oldest -> newest for reading order
    filtered.sort(key=lambda x: entry_datetime_utc(x))

    # Safety cap
    to_send = filtered[:MAX_ITEMS_PER_RUN]

    # Respect explicit thread envs first
    explicit_thread = bool(DISCORD_THREAD_ID or DISCORD_THREAD_NAME)

    # Determine behavior by mode
    mode = DISCORD_FORUM_MODE
    embeds = [to_discord_embed(e) for e in to_send]

    if explicit_thread:
        ok, _ = post_to_discord(embeds)
        if ok:
            if not FORCE_POST:
                ids = [entry_fingerprint(e) for e in to_send]
                save_state(ids, STATE_FILE)
            return 0
        return 2

    if mode == "per-item":
        all_ok = True
        posted_ids: list[str] = []
        for entry in to_send:
            embed = to_discord_embed(entry)
            thread_title = derive_thread_name(entry)
            ok_one, _ = post_to_discord([embed], thread_name=thread_title)
            if ok_one:
                posted_ids.append(entry_fingerprint(entry))
            else:
                all_ok = False
        if posted_ids and not FORCE_POST:
            save_state(posted_ids, STATE_FILE)
        return 0 if all_ok else 2

    if mode == "single":
        # Use a single derived title for the batch
        thread_title = derive_thread_name(to_send[0])
        ok, _ = post_to_discord(embeds, thread_name=thread_title)
        if ok:
            if not FORCE_POST:
                ids = [entry_fingerprint(e) for e in to_send]
                save_state(ids, STATE_FILE)
            return 0
        return 2

    if mode == "off":
        # Just try batch; do not auto-fallback to per-item
        ok, _ = post_to_discord(embeds)
        if ok:
            if not FORCE_POST:
                ids = [entry_fingerprint(e) for e in to_send]
                save_state(ids, STATE_FILE)
            return 0
        return 2

    # auto (default): first try creating a single thread with an AI-derived title;
    # if that fails (e.g., not a forum channel), fallback to posting each item without thread names.
    thread_title = derive_thread_name(to_send[0])
    ok, _ = post_to_discord(embeds, thread_name=thread_title)
    if ok:
        if not FORCE_POST:
            ids = [entry_fingerprint(e) for e in to_send]
            save_state(ids, STATE_FILE)
        return 0
    # Fallback: per-item, no thread_name
    all_ok = True
    posted_ids = []
    for entry in to_send:
        embed = to_discord_embed(entry)
        ok_one, _ = post_to_discord([embed])
        if ok_one:
            posted_ids.append(entry_fingerprint(entry))
        else:
            all_ok = False
    if posted_ids and not FORCE_POST:
        save_state(posted_ids, STATE_FILE)
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
