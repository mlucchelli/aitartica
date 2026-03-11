# Antartia — Claude Code Context

## Project summary

Antartia is an autonomous AI agent running on-device during an Antarctic expedition (March–April 2026, aboard the MV Ortelius). It manages GPS tracking, photo analysis, weather monitoring, knowledge accumulation, and publishing to an expedition website. All inference is local via Ollama; the only external calls are to Open-Meteo (weather) and the Railway-hosted expedition API.

## Architecture patterns

### Recursive tool chaining
The LLM emits actions in sequence. Each non-final action is executed and its result appended to the message context before the LLM is re-invoked. `finish` terminates the chain. Max depth: 6. Never hardcode orchestration — the LLM decides what to call and in what order.

### Execution semaphore
4 states: `idle → user_typing → llm_running → task_running`. The HTTP server (GPS receiver) never touches the semaphore. The scheduler only fires when idle. CLI holds the lock from prompt display through the final `finish`.

### Task queue
DB-backed FIFO in the `tasks` table. Both the LLM (via `create_task`) and the HTTP server enqueue tasks. The scheduler picks the oldest pending task each tick.

### Retry queue
`sync_queue` table handles failed remote pushes with up to 100 retries. Photo items store `file_path` + `payload_json` (JSON with all metadata including `file_name`). JSON items store the full payload. `retry_pending()` runs every scheduler tick.

## Timezone — critical

**Argentina time (UTC-3) everywhere for date calculations.**

- Timestamps stored as UTC ISO strings in DB (`datetime.now(timezone.utc).isoformat()`)
- "Today" and date filtering use Argentina timezone via `agent.utils.tz`
- SQL queries use UTC range bounds, never `date(col) = ?`
- `AGENT_TIMEZONE` env var → `src/agent/utils/tz.py` → `AGENT_TZ`, `today_arg()`, `day_utc_bounds()`

```python
# Always use this pattern for date-filtered queries:
from agent.utils.tz import day_utc_bounds, today_arg
start, end = day_utc_bounds(today_arg())
# WHERE col >= ? AND col < ?  with (start, end)
```

**Never** use `date(col) = ?` in SQL — it compares UTC date, which mismatches Argentina date after 21:00 local.

## DB conventions

- All timestamps: `datetime.now(timezone.utc).isoformat()` → stored as `"2026-03-11T23:30:00+00:00"`
- All "today" boundaries: computed from `AGENT_TZ` via `day_utc_bounds()`
- Migrations: `ALTER TABLE ... ADD COLUMN` wrapped in `try/except` in `database.py`
- Repos are pure DB objects — no config access. Use `agent.utils.tz` for timezone needs.

## Remote sync — `/api/photos`

- Multipart POST: field `file` (binary) + field `metadata` (JSON string)
- `file_name` MUST be inside the `metadata` JSON, not as a separate form field
- Retry path: use `meta.get("file_name")` — never `pop()` — so file_name stays in metadata
- Log response body on `httpx.HTTPStatusError` to diagnose 4xx errors

## Models

| Role | Model |
|------|-------|
| Chat LLM | `qwen3.5:9b` via Ollama |
| Vision + scoring | `qwen2.5vl:3b` via Ollama (merged single call) |
| Embeddings | `nomic-embed-text` via Ollama |

Vision and scoring run in a single LLM invocation — the scoring prompt requests both `significance_score` and `agent_quote` as JSON alongside the description.

## Key files

```
src/agent/
├── utils/tz.py              — AGENT_TZ, today_arg(), day_utc_bounds() — timezone source of truth
├── config/loader.py         — Config models; timezone reads from AGENT_TIMEZONE env
├── db/
│   ├── database.py          — DB init + all migrations
│   ├── sync_queue_repo.py   — enqueue() + enqueue_photo() + retry helpers
│   └── reflections_repo.py  — daily reflections (unique per date)
├── services/
│   ├── remote_sync_service.py  — push() + push_photo() + retry_pending()
│   ├── reflection_service.py   — gathers daily data → LLM → saves reflection
│   ├── photo_service.py        — scan → preprocess → vision+score → move → queue upload
│   └── route_analysis_service.py — Haversine bearing/speed/wind + nearest sites
├── runtime/
│   ├── scheduler.py         — tick loop; triggers: weather, reflection, route analysis, sync retry
│   └── task_runner.py       — dispatches all task types
└── llm/
    └── prompt_builder.py    — injects Argentina local time into system prompt
```

## Config structure

All behavior in `configs/expedition_config.json`. Sensitive values from env vars (`.env`). Key env vars:
- `AGENT_TIMEZONE` — timezone (default: `America/Argentina/Buenos_Aires`)
- `DB_PATH`, `OLLAMA_URL`, `PHOTO_*_DIR`, `KNOWLEDGE_*_DIR`
- `SERVER_HOST`, `REMOTE_SYNC_API_KEY` — expedition website API
- `HTTP_HOST`, `HTTP_PORT` — GPS receiver

## Scheduled routines

| Trigger | Action |
|---------|--------|
| Every tick (60s) | `retry_pending()` — sync queue retries |
| 3h, 9h, 15h, 21h Argentina | `fetch_weather` task |
| 9h, 21h Argentina | `analyze_route` task → auto-publishes progress + route + weather |
| 21h Argentina | `create_reflection` task → auto-publishes |

## Coding conventions

- `async/await` throughout — `aiosqlite`, `httpx.AsyncClient`
- Constructor injection for all services: `Service(config, db, output)`
- Protocols (`LLMClient`, `OutputHandler`) for swappable implementations
- No mocking in tests — use real DB (in-memory SQLite if needed)
- Argentina date boundaries via `day_utc_bounds()`, never raw `date()` in SQL

## What NOT to do

- Never use `date(col) = ?` in SQL — use UTC range bounds
- Never `pop("file_name")` from metadata before serializing for `/api/photos`
- Never skip `finish` at the end of an agent chain
- Never raise exceptions from `push()` or `push_photo()` — return `{"ok": False, "error": ...}`
- Never hardcode `-3 hours` offsets — use `AGENT_TZ` from `utils/tz.py`
