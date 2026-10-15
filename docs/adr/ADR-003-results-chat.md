# ADR-003: One chat over the existing inference port

## Status: Accepted

## Context

Model setup could validate a backend and, for Hugging Face, download weights, but the reply was a download path rather than generated text. Gemini selector calls still used the retired `gemini-pro` and `gemini-pro-vision` ids. There was no way to ask about the rows on screen or the sessions already stored by DatabaseManager, or to turn that answer into the next search, scrape, or watch.

## Decision

- Hugging Face generation stays behind Confirm. A local `transformers` install downloads the snapshot and generates from it. Without that install, the Hub inference client is tried, and the user is told to install `transformers`. The missing-package line for `huggingface_hub` does not change.
- Gemini text and selector calls try `gemini-2.5-flash`, then `gemini-2.5-flash-lite`, then `gemini-2.0-flash`.
- A domain chat module builds the prompt and parses only `search`, `scrape`, and `watch`. Private URLs and unknown dork types are dropped. Dork types stay `files`, `configs`, `social`, `login`, `directory`, and `email_lists`.
- The chat reads the live results cache and `DatabaseManager.get_history` / `get_results_for_session`. It does not change the schema.
- Choosing an option runs the existing crawl or `add_watch_item`. The model does not run a tool by itself.
- The confirmed model is stored in `model_config.json`. That file has no API key.

## Consequences (Positive / Negative / Neutral)

- Positive: one chat works with the saved backend, and with Gemini when the local model cannot answer. Follow-up buttons work even when both are down.
- Negative: a local Hugging Face answer needs `transformers` and the weights, or a Hub token. The first local run can be slow.
- Neutral: Gemini remains optional. Search, scrape, and watch behavior is otherwise unchanged.

## Supports: FR-003 FR-004 FR-005

## Validation: Testability | Security
