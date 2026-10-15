"""Chat about saved and current results, and the next search, scrape, or watch.

The model may only propose tools the scraper already has. Parsing drops
anything else, including a private URL or a dork type this app does not use.
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from src.domain.url_guard import is_public_http_url


DORK_TYPES = ("files", "configs", "social", "login", "directory", "email_lists")
ACTIONS = ("search", "scrape", "watch")

SPECIALIST_PROMPT = """You are the assistant for this scraper. You only help with three tools that already exist:
- search: a public web search. Add names, places, or other terms from the results to go deeper. dork_type may be empty, or one of: files, configs, social, login, directory, email_lists.
- scrape: fetch one public http or https page that is already in the results or that the user named.
- watch: monitor one public page for a keyword, or for a price when watch_mode is price.

Use the current results and the saved sessions. Say what they show, including what changed between past and present. Then offer the next search, scrape, or watch.
Do not invent logins, captchas, stealth, or new dork types.
End with one JSON object and no other text after it:
{"actions":[{"action":"search","label":"short button","detail":"why this helps","keyword":"words to search","url":"","dork_type":"","watch_mode":"keyword"}]}
Use at most 4 actions. Every action must be search, scrape, or watch.
"""

_STOP = {
    "about", "after", "again", "agree", "also", "and", "are", "back", "been", "click",
    "cookie", "cookies", "destination", "facebook", "from", "google", "have", "here",
    "home", "http", "https", "instagram", "into", "just", "linkedin", "loading",
    "login", "menu", "minute", "minutes", "more", "official", "page", "please",
    "privacy", "profile", "read", "redirect", "search", "second", "seconds", "share",
    "sign", "site", "that", "the", "their", "them", "then", "these", "this", "those",
    "twitter", "wait", "watch", "what", "when", "where", "which", "wikipedia", "with",
    "www", "youtube", "your",
}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'+-]{2,}")


@dataclass(frozen=True)
class GuidedAction:
    action: str
    label: str
    detail: str
    keyword: str = ""
    url: str = ""
    dork_type: str = ""
    watch_mode: str = "keyword"


@dataclass(frozen=True)
class ChatReply:
    text: str
    actions: tuple = ()


def build_prompt(question: str, present: list, past: list, saved: list, history: list) -> str:
    """Instructions plus a short view of the rows the user can already see."""
    parts = [
        SPECIALIST_PROMPT.strip(),
        "",
        _section("Current results", _result_lines(present, 8)),
        _section("Saved sessions", _session_lines(past, 6)),
        _section("Saved rows from earlier sessions", _result_lines(saved, 6)),
        _section("Conversation", _history_lines(history)),
        "Question:",
        _clip(question, 500),
    ]
    return "\n".join(parts)


def parse_model_reply(text: str) -> tuple:
    """Split an answer from a trailing JSON action list. Invalid actions are dropped."""
    raw = (text or "").strip()
    if not raw:
        return "", ()
    payload, start, end = _extract_payload(raw)
    actions = _actions_from_payload(payload)
    if start is None:
        return raw, actions
    prose = (raw[:start] + raw[end:]).strip()
    return prose, actions


def suggest_actions(question: str, present: list, past: list, saved: list | None = None) -> tuple:
    """Options built only from rows already on screen or in history."""
    rows = list(present or []) + list(saved or [])
    base = _base_keyword(question, past)
    added = _added_terms(base, rows, question)
    deeper = " ".join(part for part in (base, added) if part).strip()
    actions = []
    if deeper:
        label = "Search again" if deeper == base else "Search deeper"
        actions.append(_make(
            "search",
            f"{label}: {_clip(deeper, 72)}",
            "Runs the existing search with terms taken from these results. The new run replaces the on-screen rows. Earlier rows stay in History.",
            keyword=_clip(deeper, 240),
        ))
    if base:
        actions.append(_make(
            "search",
            f"Search social profiles: {_clip(base, 60)}",
            "Same public search, using the social dork already in this app.",
            keyword=_clip(base, 240),
            dork_type="social",
        ))
    for url in _public_urls(rows, past)[:2]:
        actions.append(_make(
            "scrape",
            f"Scrape {_clip(url, 64)}",
            "Fetches this public page with the existing crawler.",
            keyword=_clip(base, 240),
            url=url,
        ))
        actions.append(_make(
            "watch",
            f"Watch {_clip(url, 64)}",
            "Adds this public page to the watchdog.",
            keyword=_clip(base, 240) or (urlparse(url).hostname or "page"),
            url=url,
            watch_mode="keyword",
        ))
    return _unique(actions)[:6]


def offline_reply(question: str, present: list, past: list, saved: list | None = None, error: str = "") -> ChatReply:
    """A factual brief when no model is available. The options still run the real tools."""
    lines = []
    if error:
        lines.append(error.strip())
    lines.append(f"Current results: {len(list(present or []))}. Saved sessions: {len(list(past or []))}.")
    sessions = _session_lines(past, 4)
    if sessions:
        lines.append("Past searches: " + "; ".join(sessions))
    titles = _result_lines(list(present or []) + list(saved or []), 5)
    if titles:
        lines.append("Titles: " + "; ".join(titles))
    lines.append("The choices below run a deeper search, a scrape of a public page, or a watch. Each one uses a tool already in this app.")
    return ChatReply("\n".join(lines), suggest_actions(question, present, past, saved))


def action_from_mapping(item: dict) -> GuidedAction | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("action") or "").strip().lower()
    if kind not in ACTIONS:
        return None
    keyword = _clip(item.get("keyword"), 240)
    url = _clip(item.get("url"), 500)
    dork = str(item.get("dork_type") or "").strip().lower()
    if dork not in DORK_TYPES:
        dork = ""
    watch_mode = str(item.get("watch_mode") or "keyword").strip().lower()
    if watch_mode not in {"keyword", "price"}:
        watch_mode = "keyword"
    if kind == "search" and not keyword:
        return None
    if kind in {"scrape", "watch"} and not is_public_http_url(url):
        return None
    if kind == "watch" and watch_mode != "price" and not keyword:
        keyword = urlparse(url).hostname or "page"
    label = _clip(item.get("label"), 80) or _default_label(kind, keyword, url)
    detail = _clip(item.get("detail"), 240) or _default_detail(kind)
    return GuidedAction(kind, label, detail, keyword, url, dork, watch_mode)


def _make(kind: str, label: str, detail: str, keyword: str = "", url: str = "", dork_type: str = "", watch_mode: str = "keyword") -> GuidedAction:
    return GuidedAction(kind, label, detail, keyword, url, dork_type, watch_mode)


def _actions_from_payload(payload) -> tuple:
    if not isinstance(payload, dict):
        return ()
    found = []
    for item in payload.get("actions") or []:
        action = action_from_mapping(item)
        if action is not None:
            found.append(action)
    return tuple(_unique(found)[:6])


def _extract_payload(text: str):
    found = None
    for blob, start, end in _all_objects(text):
        parsed = _loads(blob)
        if parsed is not None:
            found = (parsed, start, end)
    if found is None:
        return None, None, None
    return found


def _loads(blob: str):
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "actions" in parsed:
        return parsed
    return None


def _all_objects(text: str):
    start = None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:index + 1], start, index + 1


def _result_lines(rows: list, limit: int) -> list:
    lines = []
    for row in list(rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        title = _clip(row.get("Title") or row.get("title") or "untitled", 180)
        price = _clip(row.get("Price") or row.get("price") or "", 40)
        link = _clip(row.get("Link") or row.get("link") or row.get("SourceURL") or row.get("source_url") or "", 180)
        extra = f" | {price}" if price else ""
        lines.append(f"{title}{extra} | {link}".strip())
    return lines


def _session_lines(rows: list, limit: int) -> list:
    lines = []
    for row in list(rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        when = _clip(row.get("timestamp") or "", 32)
        mode = _clip(row.get("mode") or "", 24)
        keyword = _clip(row.get("keyword") or "", 120)
        items = row.get("items") or row.get("total_items") or 0
        lines.append(f"{when} {mode} {keyword} ({items} items)".strip())
    return lines


def _history_lines(history: list) -> list:
    lines = []
    for item in list(history or [])[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        who = "User" if role == "user" else "Assistant"
        lines.append(f"{who}: {_clip(item.get('text'), 400)}")
    return lines


def _section(title: str, lines: list) -> str:
    body = "\n".join(f"- {line}" for line in lines) if lines else "- none"
    return f"{title}:\n{body}"


def _base_keyword(question: str, past: list) -> str:
    for row in past or []:
        if not isinstance(row, dict):
            continue
        keyword = _clip(row.get("keyword"), 240)
        if keyword and not keyword.lower().startswith(("http://", "https://")):
            return keyword
    words = [word for word in _TOKEN.findall(question or "") if word.lower() not in _STOP]
    return _clip(" ".join(words[:6]), 240)


def _added_terms(base: str, rows: list, question: str) -> str:
    """Extra search words are capitalized names and places, not page chrome."""
    known = {token.lower() for token in _TOKEN.findall(base or "")}
    counts = {}
    sources = []
    for row in list(rows or [])[:8]:
        if isinstance(row, dict):
            sources.append(str(row.get("Title") or row.get("title") or ""))
    sources.append(question or "")
    for source in sources:
        for token in _TOKEN.findall(source):
            if not token[:1].isupper() or "'" in token:
                continue
            low = token.lower()
            if low in known or low in _STOP or len(low) < 3:
                continue
            counts[low] = counts.get(low, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], -len(word), word))
    return " ".join(ranked[:3])


def _public_urls(rows: list, past: list) -> list:
    found = []
    candidates = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in ("Link", "link", "SourceURL", "source_url"):
            candidates.append(row.get(key))
    for row in past or []:
        if isinstance(row, dict):
            candidates.append(row.get("keyword"))
    for value in candidates:
        url = _clip(value, 500)
        if url and is_public_http_url(url):
            _remember_url(found, url)
    return found


def _remember_url(found: list, url: str):
    for index, earlier in enumerate(found):
        if _same_page(earlier, url):
            if len(url) < len(earlier):
                found[index] = url
            return
    found.append(url)


def _same_page(left: str, right: str) -> bool:
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if not long.startswith(short):
        return False
    return long[len(short):len(short) + 1] in {"", "?", "#"}


def _unique(actions: list) -> list:
    seen = set()
    kept = []
    for action in actions:
        key = (action.action, action.keyword.lower(), action.url, action.dork_type, action.watch_mode)
        if key in seen:
            continue
        seen.add(key)
        kept.append(action)
    return kept


def _default_label(kind: str, keyword: str, url: str) -> str:
    if kind == "search":
        return f"Search: {_clip(keyword, 60)}"
    if kind == "scrape":
        return f"Scrape {_clip(url, 60)}"
    return f"Watch {_clip(url, 60)}"


def _default_detail(kind: str) -> str:
    if kind == "search":
        return "Runs the existing search with these words."
    if kind == "scrape":
        return "Fetches this public page with the existing crawler."
    return "Adds this public page to the watchdog."


def _clip(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
