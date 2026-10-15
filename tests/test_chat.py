import json

import src.ai_helper as ai_helper
from src.application.chat import (
    ask_about_results,
    backend_label,
    local_complete,
    plan_action,
    records_from_rows,
    sessions_from_history,
)
from src.domain.chat import (
    DORK_TYPES,
    SPECIALIST_PROMPT,
    ChatReply,
    GuidedAction,
    action_from_mapping,
    build_prompt,
    parse_model_reply,
    suggest_actions,
)
from src.domain.inference import InferenceResult, ModelConfig
from src.infrastructure.model_store import load_model_config, save_model_config
from src.osint_helper import DORKS


PRESENT = [
    {
        "Title": "Ada Lovelace Exampleville coach",
        "Price": "",
        "Link": "https://example.com/grace",
        "SourceURL": "https://example.com/grace",
    }
]
PAST = [{"timestamp": "2026-01-02", "mode": "osint", "keyword": "Ada Lovelace", "items": 3}]


def test_dork_types_match_the_existing_templates():
    assert tuple(DORKS) == DORK_TYPES
    for name in ("files", "configs", "social", "login", "directory", "email_lists"):
        assert name in SPECIALIST_PROMPT
    assert "search" in SPECIALIST_PROMPT
    assert "scrape" in SPECIALIST_PROMPT
    assert "watch" in SPECIALIST_PROMPT


def test_prompt_includes_past_and_present_rows():
    prompt = build_prompt("What changed?", PRESENT, PAST, [], [])
    assert "Ada Lovelace Exampleville coach" in prompt
    assert "Ada Lovelace" in prompt
    assert "What changed?" in prompt
    assert "https://example.com/grace" in prompt


def test_parser_keeps_only_real_tools_and_public_pages():
    raw = """
    Two public pages mention Ada.
    ```json
    {"actions":[
      {"action":"search","label":"Search Ada","detail":"deeper","keyword":"Ada school","url":"","dork_type":"passwords","watch_mode":"keyword"},
      {"action":"scrape","label":"Scrape","detail":"page","keyword":"","url":"https://example.com/ada","dork_type":"","watch_mode":"keyword"},
      {"action":"scrape","label":"Local","detail":"no","keyword":"","url":"http://127.0.0.1/admin","dork_type":"","watch_mode":"keyword"},
      {"action":"exfiltrate","label":"No","detail":"no","keyword":"secret","url":"","dork_type":"","watch_mode":"keyword"}
    ]}
    ```
    """
    prose, actions = parse_model_reply(raw)
    assert "Two public pages" in prose
    assert [item.action for item in actions] == ["search", "scrape"]
    assert actions[0].dork_type == ""
    assert actions[0].keyword == "Ada school"
    assert actions[1].url == "https://example.com/ada"
    assert action_from_mapping({"action": "watch", "url": "http://10.1.1.1/a", "keyword": "Ada"}) is None


def test_suggestions_add_terms_from_the_results():
    actions = suggest_actions("Where else does this show up?", PRESENT, PAST, [])
    searches = [item for item in actions if item.action == "search"]
    assert searches[0].keyword.startswith("Ada Lovelace")
    assert "exampleville" in searches[0].keyword
    assert searches[1].dork_type == "social"
    assert any(item.action == "scrape" and item.url == "https://example.com/grace" for item in actions)
    assert any(item.action == "watch" and item.url == "https://example.com/grace" for item in actions)
    assert all(item.action in {"search", "scrape", "watch"} for item in actions)


def test_suggestions_skip_page_chrome_and_tracking_links():
    rows = [
        {"Title": "We'll be back in a few seconds Destination", "Link": "https://example.com/ada"},
        {"Title": "Ada Lovelace", "Link": "https://example.com/ada?fbclid=1&utm_source=x"},
    ]
    past = [{"keyword": "Ada Lovelace", "mode": "osint", "items": 1, "timestamp": "2026-01-01"}]
    actions = suggest_actions("where else?", rows, past, [])
    search = next(item for item in actions if item.action == "search" and not item.dork_type)
    assert search.keyword == "Ada Lovelace"
    assert "seconds" not in search.keyword
    assert "destination" not in search.keyword
    scrapes = [item.url for item in actions if item.action == "scrape"]
    assert scrapes == ["https://example.com/ada"]


def test_ask_uses_the_model_then_keeps_a_guided_option():
    def complete(prompt):
        assert "Ada Lovelace" in prompt
        payload = {
            "actions": [
                {
                    "action": "search",
                    "label": "Search school",
                    "detail": "Add the school from the title.",
                    "keyword": "Ada Lovelace Exampleville",
                    "url": "",
                    "dork_type": "files",
                    "watch_mode": "keyword",
                }
            ]
        }
        return InferenceResult(True, "The current title adds Exampleville.\n" + json.dumps(payload), "")

    reply = ask_about_results("What is new?", PRESENT, PAST, [], [], complete)
    assert "Exampleville" in reply.text
    assert reply.actions[0].dork_type == "files"
    assert reply.actions[0].keyword == "Ada Lovelace Exampleville"
    assert any(item.action == "scrape" for item in reply.actions)


def test_ask_falls_back_and_still_offers_tools_when_both_fail():
    calls = []

    def complete(_prompt):
        calls.append("local")
        return InferenceResult(False, "", "Confirm a model in Model setup before this chat can use it.")

    def fallback(_prompt):
        calls.append("gemini")
        return InferenceResult(False, "", "Gemini API key is missing.")

    reply = ask_about_results("What is new?", PRESENT, PAST, [], [], complete, fallback)
    assert calls == ["local", "gemini"]
    assert "Confirm a model" in reply.text
    assert "Gemini API key is missing." in reply.text
    assert reply.actions
    assert any(item.action == "search" for item in reply.actions)


def test_plan_runs_search_scrape_or_watch_and_refuses_a_private_page():
    search = plan_action(GuidedAction("search", "Search", "why", "Ada school", "", "social"))
    assert search.ok is True
    assert search.mode == "osint"
    assert search.dork_type == "social"
    scrape = plan_action(GuidedAction("scrape", "Scrape", "why", "Ada", "https://example.com/ada"))
    assert scrape.mode == "custom"
    assert scrape.url == "https://example.com/ada"
    watch = plan_action(GuidedAction("watch", "Watch", "why", "12.50", "https://example.com/ada", "", "price"))
    assert watch.mode == "watchdog"
    assert watch.watch_mode == "price"
    assert watch.target_price == 12.50
    refused = plan_action(GuidedAction("scrape", "Scrape", "why", "", "http://localhost/secret"))
    assert refused.ok is False


def test_rows_and_history_keep_their_public_shape():
    records = records_from_rows([
        ["9", "Ada", "$2", "", "", "", "https://example.com/ada", "", "https://example.com/ada"]
    ])
    assert records[0]["Title"] == "Ada"
    assert records[0]["Link"] == "https://example.com/ada"
    sessions = sessions_from_history([("abc", "2026-01-02", "Ada", "osint", 4)])
    assert sessions[0]["keyword"] == "Ada"
    assert sessions[0]["items"] == 4


def test_unconfirmed_model_is_not_called():
    def build(_config):
        raise AssertionError("an unconfirmed model must not be built")

    result = local_complete(ModelConfig("huggingface", "org/model"), "hello", build)
    assert result.ok is False
    assert "Confirm" in result.error


def test_model_config_round_trip_has_no_secret(tmp_path):
    path = tmp_path / "model_config.json"
    save_model_config(ModelConfig("ollama", "llama3.2", "", "http://127.0.0.1:11434", confirmed=True), path)
    loaded = load_model_config(path)
    assert loaded == ModelConfig("ollama", "llama3.2", "", "http://127.0.0.1:11434", confirmed=True)
    assert "api_key" not in path.read_text(encoding="utf-8")
    assert load_model_config(tmp_path / "missing.json") is None
    assert backend_label(loaded, False) == "ollama: llama3.2"
    assert "Gemini 2.5 Flash" in backend_label(None, True)


def test_gemini_text_skips_a_failed_model(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, name):
            self.name = name
            calls.append(name)

        def generate_content(self, _content):
            if self.name != "gemini-2.5-flash-lite":
                raise RuntimeError("gone")
            return type("Reply", (), {"text": "two phones on file"})()

    monkeypatch.setattr(ai_helper.genai, "GenerativeModel", Fake)
    monkeypatch.setattr(ai_helper.genai, "configure", lambda api_key: None)
    text, err = ai_helper.generate_text("summarize the rows", api_key="not-a-real-key")
    assert err is None
    assert text == "two phones on file"
    assert calls[0] == "gemini-2.5-flash"
    assert "gemini-pro" not in ai_helper.GEMINI_TEXT_MODELS
    assert "gemini-pro-vision" not in ai_helper.GEMINI_TEXT_MODELS


def test_css_selector_uses_a_current_gemini_model(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, name):
            calls.append(name)

        def generate_content(self, _content):
            return type("Reply", (), {"text": "div.price"})()

    monkeypatch.setattr(ai_helper.genai, "GenerativeModel", Fake)
    selector, err = ai_helper.generate_css_selector("<div class='price'>1</div>", "price")
    assert err is None
    assert selector == "div.price"
    assert calls[0] == "gemini-2.5-flash"


def test_chat_window_asks_and_runs_the_chosen_step():
    import time

    try:
        import ttkbootstrap as ttkb
        root = ttkb.Window(themename="superhero")
    except Exception:
        import tkinter as tk
        root = tk.Tk()
    root.withdraw()
    asked = {}
    ran = {}

    def ask(question, history):
        asked["question"] = question
        asked["history"] = history
        return ChatReply(
            "The title adds Exampleville.",
            (GuidedAction("search", "Search deeper: Ada Lovelace exampleville", "Add the school.", "Ada Lovelace exampleville"),),
        )

    def run_action(action):
        ran["action"] = action.action
        ran["keyword"] = action.keyword
        return f"Starting a deeper search for {action.keyword}."

    from src.presentation.chat_window import ChatWindow

    window = ChatWindow(
        root,
        ask=ask,
        run_action=run_action,
        opening=ChatReply("Current results: 1. Saved sessions: 1.", ()),
        backend_label="ollama: llama3.2",
    )
    window.withdraw()
    try:
        window.update_idletasks()
        transcript = window.transcript.get("1.0", "end")
        assert "Current results: 1." in transcript
        assert asked == {}
        window.input_var.set("What changed since last time?")
        window._send()
        for _ in range(100):
            window.update()
            if "Exampleville" in window.transcript.get("1.0", "end"):
                break
            time.sleep(0.02)
        transcript = window.transcript.get("1.0", "end")
        assert "What changed since last time?" in transcript
        assert "The title adds Exampleville." in transcript
        assert asked["question"] == "What changed since last time?"
        assert window._option_buttons
        window._option_buttons[0].invoke()
        window.update_idletasks()
        assert ran["action"] == "search"
        assert ran["keyword"] == "Ada Lovelace exampleville"
        assert "Starting a deeper search" in window.transcript.get("1.0", "end")
    finally:
        window.destroy()
        root.destroy()
        try:
            import ttkbootstrap as ttkb
            ttkb.Style.instance = None
        except Exception:
            pass
