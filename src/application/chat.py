"""Turn result rows into a model prompt, and a chosen option into a crawl plan."""
from dataclasses import dataclass

from src.domain.chat import (
    DORK_TYPES,
    ChatReply,
    GuidedAction,
    build_prompt,
    offline_reply,
    parse_model_reply,
    suggest_actions,
)
from src.domain.inference import InferenceResult, ModelConfig
from src.domain.url_guard import is_public_http_url


RESULT_FIELDS = ("Match", "Title", "Price", "Rating", "Shipping", "Entities", "Link", "ImageURL", "SourceURL")


@dataclass(frozen=True)
class ActionPlan:
    ok: bool
    message: str
    mode: str = ""
    keyword: str = ""
    url: str = ""
    dork_type: str = ""
    watch_mode: str = ""
    target_price: float = 0.0


def records_from_rows(rows) -> list:
    """Accept dict rows or the on-screen column tuples."""
    records = []
    for row in rows or []:
        if isinstance(row, dict):
            records.append(row)
            continue
        if isinstance(row, (list, tuple)):
            records.append({field: row[index] if index < len(row) else "" for index, field in enumerate(RESULT_FIELDS)})
    return records


def sessions_from_history(rows) -> list:
    """Map DatabaseManager.get_history tuples without touching the database."""
    sessions = []
    for row in rows or []:
        if isinstance(row, dict):
            sessions.append(row)
            continue
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            sessions.append({
                "session_id": row[0],
                "timestamp": row[1],
                "keyword": row[2],
                "mode": row[3],
                "items": row[4],
            })
    return sessions


def backend_label(config: ModelConfig | None, gemini_ready: bool) -> str:
    if config is not None and (config.backend or "").strip():
        target = config.model_id or config.model_path or config.endpoint or "configured"
        return f"{config.backend}: {target}"
    if gemini_ready:
        return "Gemini 2.5 Flash (no local model saved)"
    return "No model configured. Suggestions still run search, scrape, and watch."


def opening_reply(present: list, past: list, saved: list | None = None) -> ChatReply:
    return offline_reply("", present, past, saved)


def local_complete(config: ModelConfig | None, prompt: str, build) -> InferenceResult:
    """Run a saved backend. Chat never downloads a model that has not been confirmed."""
    if config is None or not config.confirmed:
        return InferenceResult(False, "", "Confirm a model in Model setup before this chat can use it.")
    return build(config).complete(prompt, max_tokens=400)


def ask_about_results(question: str, present: list, past: list, saved: list, history: list, complete, fallback=None) -> ChatReply:
    """Ask the configured model, then Gemini. A failure still returns real tool options."""
    question = " ".join(str(question or "").split())
    if not question:
        return opening_reply(present, past, saved)
    prompt = build_prompt(question, present, past, saved, history)
    primary = _call(complete, prompt)
    result = primary
    if not primary.ok and fallback is not None:
        result = _call(fallback, prompt)
        if not result.ok:
            error = " ".join(part for part in (primary.error, result.error) if part)
            result = InferenceResult(False, "", error or "The model did not answer.")
    if not result.ok:
        return offline_reply(question, present, past, saved, error=result.error or "The model did not answer.")
    prose, actions = parse_model_reply(result.text)
    merged = _merge(actions, suggest_actions(question, present, past, saved))
    if not prose:
        prose = "Here is what these results support, and the next search, scrape, or watch."
    return ChatReply(prose, tuple(merged[:6]))


def plan_action(action: GuidedAction) -> ActionPlan:
    """Describe one existing tool run. The caller performs it."""
    kind = (action.action or "").strip().lower()
    keyword = " ".join(str(action.keyword or "").split())
    url = " ".join(str(action.url or "").split())
    dork = action.dork_type if action.dork_type in DORK_TYPES else ""
    if kind == "search":
        if not keyword:
            return ActionPlan(False, "A search needs words to look for.")
        return ActionPlan(True, f"Starting a deeper search for {keyword}.", "osint", keyword, "", dork)
    if kind == "scrape":
        if not is_public_http_url(url):
            return ActionPlan(False, "Scrape only a public http or https page.")
        return ActionPlan(True, f"Scraping {url}.", "custom", keyword, url)
    if kind == "watch":
        if not is_public_http_url(url):
            return ActionPlan(False, "Watch only a public http or https page.")
        if action.watch_mode == "price":
            try:
                target = float(keyword)
            except (TypeError, ValueError):
                return ActionPlan(False, "A price watch needs a numeric target.")
            return ActionPlan(True, f"Watching {url} for a price at or below {target}.", "watchdog", keyword, url, "", "price", target)
        if not keyword:
            return ActionPlan(False, "A keyword watch needs a word to look for.")
        return ActionPlan(True, f"Watching {url} for {keyword}.", "watchdog", keyword, url, "", "keyword", 0.0)
    return ActionPlan(False, "That action is not available.")


def _merge(primary, extra) -> list:
    return _dedupe(list(primary or []) + list(extra or []))


def _dedupe(actions: list) -> list:
    seen = set()
    kept = []
    for action in actions:
        key = (action.action, action.keyword.lower(), action.url, action.dork_type, action.watch_mode)
        if key in seen:
            continue
        seen.add(key)
        kept.append(action)
    return kept


def _call(complete, prompt: str) -> InferenceResult:
    if complete is None:
        return InferenceResult(False, "", "No model is configured.")
    try:
        result = complete(prompt)
    except Exception as exc:
        return InferenceResult(False, "", str(exc) or "The model did not answer.")
    if isinstance(result, InferenceResult):
        return result
    return InferenceResult(False, "", "The model did not answer.")
