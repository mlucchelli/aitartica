# Antartia

An autonomous AI agent built for Antarctic field expeditions. It runs entirely on-device — no cloud dependency for inference — and orchestrates GPS tracking, photo analysis, weather monitoring, and expedition publishing through a recursive tool-chaining loop driven by a local LLM.

---

## What it does

The agent sits in a terminal on expedition equipment (laptop, NUC) and acts as an intelligent field assistant. An iPhone sends GPS coordinates via HTTP every hour. Photos dropped into an inbox folder are automatically preprocessed, described by a vision model, scored for significance, and selectively published to an expedition website. Weather is fetched from Open-Meteo four times a day and stored. Everything — locations, photos, weather, messages — lives in a local SQLite database that survives restarts.

The agent doesn't just retrieve data: it **reasons over it**. Ask it about today's route and it will chain `get_latest_locations` → `get_weather` → `send_message` in a single turn, fetching live data before answering. Ask it to scan the photo inbox and it runs the full pipeline inline — preprocessing, vision analysis, significance scoring — streaming each step to the terminal.

---

## Architecture

### Recursive tool chaining

Every user message triggers an LLM invocation that returns a list of actions. Non-final actions (tools) are executed and their results appended to the message context. The LLM is re-invoked. This repeats until the chain emits `finish` — up to `max_chain_depth = 6` turns. The LLM decides what to fetch and in what order, naturally chaining tools without any hardcoded orchestration logic.

```
User input
  → LLM → [get_latest_locations, get_weather]
  → tool results appended
  → LLM → [send_message, finish]
  → reply displayed
```

### Execution semaphore

A single asyncio lock coordinates three concurrent subsystems: the CLI, the task scheduler, and the HTTP server. The CLI holds the lock from the moment the prompt appears through the end of the agent's reply. The scheduler runs only in the brief window between turns. The HTTP server is the only component that never touches the lock — GPS coordinates are always stored immediately, regardless of what else is happening.

```
idle → user_typing → llm_running → idle
idle → task_running → idle
HTTP server: always running, never locked
```

### Photo pipeline

Photos dropped into `data/photos/inbox/` are processed in three stages:

1. **Preprocessing** — EXIF orientation correction, resize to target dimensions (longest side 640–800px), SHA-256 fingerprint. Original is never modified.
2. **Vision analysis** — Preview sent as base64 to `qwen2.5vl:7b` via Ollama. Returns a detailed description and a one-line summary displayed in the terminal.
3. **Significance scoring** — The description is sent to a second Ollama call with a configurable scoring prompt. Score ≥ 0.75 flags the photo as a remote upload candidate.

The original is moved to `processed/` after success. The preview JPEG stays in `vision_preview/`.

```
inbox/photo.jpg
  → EXIF + resize → vision_preview/photo_preview.jpg
  → qwen2.5vl:7b → "A Chinstrap penguin stands on snow against a backdrop of the Antarctic Ocean."
  → significance score: 0.70 → archived (below threshold)
```

### Weather

Open-Meteo ECMWF IFS model — tuned for polar regions. Fetches temperature, apparent temperature, wind speed and gusts, wind direction, precipitation, snowfall, snow depth, surface pressure, and WMO weather condition code. Runs on a configurable schedule (default: 6h, 12h, 18h, 0h UTC). The CLI status bar shows the latest snapshot in real time.

### Knowledge base *(commit 19)*

A local ChromaDB instance stores semantic embeddings of expedition documents — itinerary, species guides, ship specs, location descriptions, science notes. Embedded via `nomic-embed-text` through Ollama. The `search_knowledge` action retrieves the top-5 most relevant chunks before the LLM answers expedition-specific questions.

### HTTP ingestion

A minimal asyncio HTTP server listens for `POST /locations` from an iPhone Shortcut. No framework dependency — `asyncio.start_server` with a raw request parser. GPS coordinates are inserted and a `process_location` task queued immediately, without touching the semaphore.

### Task scheduler

A 60-second tick loop that only fires when the semaphore is idle. Generates `fetch_weather` tasks at scheduled hours and executes the oldest pending task from the `tasks` table (FIFO). All task types: `process_location`, `scan_photo_inbox`, `process_photo`, `fetch_weather`, `publish_daily_progress`, `publish_route_snapshot`, `upload_image`, `publish_agent_message`, `publish_weather_snapshot`.

---

## Terminal layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Antartia: Today we covered 14km. Wind picked up at 17:00 — gusts to   │
│  62 km/h. Two photos processed: one Chinstrap penguin (archived),       │
│  one summit panorama flagged for upload.                                │
│                                                                         │
│  ⟳ inbox: found new photo — IMG_0847.jpg                               │
│  ◈ analyzing IMG_0847.jpg                                              │
│    ◈ Three expedition members approach a crevasse field at dusk.       │
│  ⟳   score=0.91 — ✓ remote candidate                                  │
│  ⟳   moved: IMG_0847.jpg → processed/                                  │
│─────────────────────────────────────────────────────────────────────────│
│ ❯                                                                       │
│ abc123 · -62.15, -58.45 · -4.2°C (feels -11.0°C) ❄                   │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Scroll area** — agent replies, tool execution steps, task progress, vision summaries
- **Input row** — `❯` prompt (or spinner during LLM/task execution)
- **Status bar** — session ID, last known GPS coordinates, temperature, feels-like, precipitation icon (❄ snow / 🌧 rain)

---

## Stack

| Layer | Technology |
|---|---|
| LLM (chat) | Ollama — any model (default: OpenRouter for cloud, Ollama for local) |
| Vision | `qwen2.5vl:7b` via Ollama |
| Significance scoring | Ollama (same vision model, text-only prompt) |
| Embeddings | `nomic-embed-text` via Ollama |
| Vector store | ChromaDB (embedded, no server) |
| Database | SQLite via `aiosqlite` |
| HTTP client | `httpx` (async) |
| Image processing | Pillow |
| Terminal UI | Rich |
| Config | Pydantic v2 + JSON |
| Weather API | Open-Meteo ECMWF IFS |

Everything runs offline except weather fetching and remote publishing. No GPU required — M3 Pro 18GB handles `qwen2.5vl:7b` + `nomic-embed-text` comfortably.

---

## Project structure

```
src/agent/
├── __main__.py              — Entry point: CLI + HTTP server + scheduler
├── config/loader.py         — Pydantic config models, all paths from env vars
├── cli/app.py               — Terminal UI: scroll area, spinner, status bar
├── db/
│   ├── database.py          — aiosqlite connection + table init
│   ├── locations_repo.py
│   ├── photos_repo.py
│   ├── weather_repo.py
│   ├── tasks_repo.py
│   └── messages_repo.py
├── http/server.py           — asyncio HTTP server (POST /locations)
├── llm/
│   ├── client.py            — LLMClient protocol
│   ├── ollama.py            — Ollama chat client (structured output)
│   ├── ollama_vision.py     — Vision client (base64 image → description + summary)
│   └── openrouter.py        — OpenRouter client
├── models/
│   ├── actions.py           — 14 action types
│   └── state.py             — ConversationState
├── runtime/
│   ├── runtime.py           — Recursive chaining loop + tool dispatch
│   ├── scheduler.py         — 60s tick, FIFO task execution
│   ├── semaphore.py         — ExecutionSemaphore (4 states)
│   ├── task_runner.py       — Dispatches task types to services
│   └── parser.py            — ACTION_REGISTRY
└── services/
    ├── photo_service.py     — Full photo pipeline
    ├── image_preprocessing.py — EXIF + resize + SHA-256
    ├── weather_service.py   — Open-Meteo fetch + DB persistence
    └── knowledge_service.py — ChromaDB + Ollama embeddings (commit 19)

configs/
└── expedition_config.json  — Full expedition agent config

data/
├── photos/inbox/            — Drop photos here
├── photos/processed/        — Originals after processing
├── photos/vision_preview/   — Derived JPEG previews
├── knowledge/               — Drop .txt/.md expedition documents here
└── expedition.db            — SQLite database
```

---

## Setup

```bash
# 1. Clone and install
git clone https://github.com/mlucchelli/antartia.git
cd antartia
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Pull Ollama models
ollama pull qwen2.5vl:7b
ollama pull nomic-embed-text

# 3. Configure environment
cp .env.example .env
# Edit .env — set DB_PATH, photo dirs, OLLAMA_URL, etc.

# 4. Run
python -m agent --config configs/expedition_config.json
```

---

## Available actions

| Action | Description |
|---|---|
| `get_latest_locations` | Fetch most recent GPS positions |
| `get_locations_by_date` | GPS positions for a specific day |
| `get_photos` | Photo records with vision descriptions and scores |
| `get_weather` | Live weather fetch + store snapshot |
| `scan_photo_inbox` | Scan inbox and run full pipeline on all photos |
| `create_task` | Queue a background task for the scheduler |
| `search_knowledge` | Semantic search over expedition knowledge base |
| `index_knowledge` | Re-index all documents in the knowledge folder |
| `publish_daily_progress` | Bundle today's data and publish to expedition site |
| `publish_route_snapshot` | Publish GeoJSON route to expedition site |
| `upload_image` | Upload a remote-candidate photo |
| `publish_agent_message` | Post a message to the expedition website |
| `publish_weather_snapshot` | Publish latest weather reading |
| `send_message` | Display text to the user (non-terminal) |
| `finish` | Terminate the chain |

---

## Example interactions

```
❯ what were today's conditions?
  ▸ reasoning...
  executing: get_latest_locations
  executing: get_weather
  ▸ reasoning... (1)
  executing: send_message
Antartia: Position: -62.18, -58.41. Temp -4.2°C (feels -11°C), wind 38 km/h SW,
          gusts to 62 km/h, light snow. Snow depth 0.12m.
  executing: finish

❯ scan the inbox
  ▸ reasoning...
  executing: scan_photo_inbox
  ⟳ inbox: found new photo — IMG_0847.jpg
  ◈ analyzing IMG_0847.jpg
  ⟳   ◈ Three expedition members approach a crevasse field at dusk.
  ⟳ scoring: IMG_0847.jpg
  ⟳   score=0.91 — ✓ remote candidate
  ⟳   moved: IMG_0847.jpg → processed/
  ▸ reasoning... (1)
  executing: send_message
Antartia: 1 photo processed. IMG_0847 flagged as remote candidate (score 0.91).
  executing: finish

❯ what species might we see near King George Island?
  ▸ reasoning...
  executing: search_knowledge
  ▸ reasoning... (1)
  executing: send_message
Antartia: Around King George Island you may encounter Chinstrap and Gentoo penguins,
          Weddell seals, leopard seals, and Wilson's storm petrels. Humpback and
          minke whales are frequent in the Maxwell Bay area during summer.
  executing: finish
```

---

## License

MIT
