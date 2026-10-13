# ADR-001: Pytest and inward layers

## Status: Accepted

## Context

The scraper at this project root has no test runner and no `tests/` tree. `src/main.py` (about 1489 lines) mixes crawling, Tk UI, and HTML report assembly. `src/report_viz.js` builds a vis-network graph with no filters. `src/ai_helper.py` talks only to Gemini. Leave `start.sh` exactly as it is, including its existing API key default.

## Decision

- Adopt pytest as the test runner. This is a new dependency because none exists.
- New behavior follows clean layers. Dependencies point inward: presentation → application → domain ← infrastructure.
- Domain modules import only the standard library.
- The HTML report and the model wizard are presentation. Graph construction and backend selection rules stay out of the Tk widgets and out of the HTML string.

## Consequences (Positive / Negative / Neutral)

- Positive: report layout and inference backends can be unit-tested without Tk or a network.
- Negative: pytest and optional inference packages are new installs. Heavy packages stay optional.
- Neutral: existing crawl, SQLite, and Gemini selector code keep working.

## Supports: FR-001 FR-002 FR-003 FR-004 FR-005

## Validation: Testability
