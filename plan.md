# Antarctic Expedition Agent

## Overview

Console-first autonomous expedition AI agent that tracks an Antarctic expedition in real time. An iPhone sends GPS coordinates via HTTP every hour; a scheduler collects weather four times daily; photos are ingested from an inbox, analyzed locally with a vision model (Ollama `qwen2.5-vl`), scored for significance via a second LLM call, and published selectively to a remote expedition website.

The LLM drives all decisions through **recursive tool chaining** — it calls tools in sequence, receives results, and keeps calling more tools before producing a final `send_message`. A shared execution semaphore prevents concurrent heavy operations. All state lives in SQLite. The existing conversational agent foundation (action-driven runtime, Pydantic models, CLI, Protocols) is extended — `collect_field` and `escalate` are not used in the expedition agent.

## Architecture

-   **Recursive Tool Chaining**: LLM emits actions → runtime executes tools → results appended to context → LLM invoked again → repeat until `send_message` or `max_chain_depth = 6`
-   **Execution Semaphore**: Four states (`idle`, `user_typing`, `llm_running`, `task_running`) — the asyncio lock is held continuously from the moment the CLI shows the `❯` prompt through the entire LLM reply; scheduler can only run in the brief window between a reply finishing and the next prompt appearing
-   **Task Scheduler**: 60-second tick loop; generates due weather tasks; picks the oldest pending task (FIFO, no priority); streams task progress to the scroll area while blocking the input prompt
-   **HTTP Server is lock-free**: the HTTP server runs completely outside the semaphore — GPS coordinates are always stored and tasks always queued regardless of what the CLI is doing
-   **HTTP Ingestion**: asyncio HTTP server (`POST /locations`) receives GPS from iPhone shortcut → inserts `process_location` task into `tasks` table
-   **Repository Pattern**: Six SQLite tables each with a dedicated async repository (`aiosqlite`); fully decoupled from conversation state
-   **All-Local LLM**: Ollama handles all LLM operations — `qwen2.5-vl` for vision description, a text model (e.g. `qwen2.5`) for chat and significance scoring; no external API calls
-   **Remote Publishing**: Railway API receives daily JSON, route snapshots, weather snapshots, selected photos, and agent messages via multipart/form-data
-   **Protocol-Based**: `LLMClient`, `StateStore`, `OutputHandler` remain swappable; all services follow constructor injection

## Execution & Semaphore Model

The semaphore lock is held for all four non-idle states. The HTTP server is the only component that never touches the semaphore.

```mermaid
graph TD
    subgraph HTTP [HTTP Server — always running, no semaphore]
        iPhone[iPhone POST /locations] --> InsertLoc[INSERT locations]
        InsertLoc --> InsertTask[INSERT tasks FIFO]
    end

    subgraph CLI [CLI — asyncio loop]
        Idle([semaphore: idle]) --> AcquireTyping[acquire_typing — lock acquired\nstate = user_typing]
        AcquireTyping --> ShowPrompt[Show ❯ prompt\nawait input in executor]
        ShowPrompt --> UserTypes[User types...]
        UserTypes --> SchedulerCheck{Scheduler tick?}
        SchedulerCheck -->|tries acquire| SkipLocked[Lock held → skip tick]
        SkipLocked --> UserTypes
        UserTypes --> Enter[User hits Enter]
        Enter --> TransitionLLM[transition_to_llm\nstate = llm_running\nlock still held]
        TransitionLLM --> ShowSpinner[Show ⠹ Thinking... spinner]
        ShowSpinner --> LLMCall[LLMClient.ainvoke]
        LLMCall --> ParseActions[Parse actions]
        ParseActions --> IsFinal{Final action?}
        IsFinal -->|tool action| ExecTool[Execute tool + stream result to scroll]
        ExecTool --> LLMCall
        IsFinal -->|send_message| Display[Display reply in scroll area]
        Display --> Release[release — state = idle\nlock released]
        Release --> AcquireTyping
    end

    subgraph Scheduler [Scheduler — 60s tick]
        Tick[60s tick] --> TryAcquire{try acquire_task}
        TryAcquire -->|lock free| RunTask[state = task_running\nlock acquired]
        TryAcquire -->|lock held| SkipTick[skip — try again in 60s]
        RunTask --> StreamProgress[Stream task progress\nto scroll area\nshow ⠹ spinner on input row]
        StreamProgress --> TaskDone[task complete / failed]
        TaskDone --> ReleaseTask[release — idle\nlock released]
        ReleaseTask --> CLI
    end
```

### Key invariant

The CLI acquires the lock **before** showing the `❯` prompt and holds it until the agent finishes replying. This means:

- **Typing** → lock held → scheduler cannot run
- **Enter pressed** → lock stays held, state transitions to `llm_running`
- **Agent replies** → lock released → scheduler gets one chance to run before CLI re-acquires for the next prompt
- **Task running** → lock held → CLI waits at `acquire_typing()` showing the spinner; task progress streams to scroll area

The HTTP server **never touches the lock** — GPS coordinates are always stored and tasks always queued, even mid-sentence.

## Conversation Flow

```mermaid
graph TD
    LLMCall[LLMClient.ainvoke] --> ParseActions[ActionParser.parse]
    ParseActions --> IsFinal{Final action?}
    IsFinal -->|send_message| Display[Display reply — release lock — idle]
    IsFinal -->|tool action| ExecTool[Execute tool]
    ExecTool --> AppendResult[Append result to context]
    AppendResult --> DepthCheck{depth >= 6?}
    DepthCheck -->|Yes| ForceSend[Force send_message]
    ForceSend --> Display
    DepthCheck -->|No| LLMCall
```

## Actions

---

### `get_latest_locations`

Returns the most recent GPS locations from the `locations` table.

```mermaid
graph TD
    LLM([LLM emits get_latest_locations]) --> ParsePayload[Parse payload: limit]
    ParsePayload --> DB[(locations table)]
    DB --> Rows[Fetch N most recent rows]
    Rows --> Format[Format as JSON list]
    Format --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with location data])
```

---

### `get_locations_by_date`

Returns all GPS locations recorded on a specific date.

```mermaid
graph TD
    LLM([LLM emits get_locations_by_date]) --> ParsePayload[Parse payload: date]
    ParsePayload --> DB[(locations table)]
    DB --> Filter[Filter by recorded_at date]
    Filter --> Format[Format as JSON list with lat/lon/time]
    Format --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with day locations])
```

---

### `get_photos`

Returns photo records from the `photos` table, optionally filtered by status or date.

```mermaid
graph TD
    LLM([LLM emits get_photos]) --> ParsePayload[Parse payload: filter optional]
    ParsePayload --> DB[(photos table)]
    DB --> Filter[Filter by status / date / candidate flag]
    Filter --> Format[Format as JSON list with description + score]
    Format --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with photo data])
```

---

### `get_weather`

Fetches current weather from Open-Meteo for given coordinates and stores a snapshot.

```mermaid
graph TD
    LLM([LLM emits get_weather]) --> ParsePayload[Parse payload: latitude, longitude]
    ParsePayload --> OpenMeteo[WeatherService: GET open-meteo API]
    OpenMeteo --> WeatherData[temperature, wind speed, condition]
    WeatherData --> DB[(weather_snapshots table)]
    DB --> Format[Format as weather summary string]
    Format --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with weather data])
```

---

### `create_task`

Inserts a new task into the `tasks` table for deferred execution by the scheduler.

```mermaid
graph TD
    LLM([LLM emits create_task]) --> ParsePayload[Parse payload: type, payload, priority]
    ParsePayload --> Validate{Valid task type?}
    Validate -->|No| Error[Return error string]
    Validate -->|Yes| DB[(tasks table)]
    DB --> Insert[INSERT task with status=pending]
    Insert --> Confirm[Return confirmation string]
    Confirm --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with confirmation])
```

---

### `scan_photo_inbox`

Triggers immediate scan of the photo inbox directory and queues `process_photo` tasks for new files.

```mermaid
graph TD
    LLM([LLM emits scan_photo_inbox]) --> ScanDir[Scan inbox_dir for .jpg .jpeg .png .webp]
    ScanDir --> DB[(photos table)]
    DB --> Filter[Filter already-indexed file_paths]
    Filter --> NewFiles{New files found?}
    NewFiles -->|No| Report[Return: inbox empty]
    NewFiles -->|Yes| Insert[INSERT new PhotoRecord per file]
    Insert --> TaskDB[(tasks table)]
    TaskDB --> Queue[INSERT process_photo task per file]
    Queue --> Report2[Return: N new files queued]
    Report2 --> AppendCtx[Append to tool result context]
    AppendCtx --> LLM2([LLM re-invoked with scan report])
```

---

### `publish_daily_progress`

Bundles today's locations, weather snapshots, and agent messages into a JSON payload and POSTs to Railway.

```mermaid
graph TD
    LLM([LLM emits publish_daily_progress]) --> FetchLoc[Fetch today locations from DB]
    FetchLoc --> FetchWeather[Fetch today weather snapshots from DB]
    FetchWeather --> FetchMsgs[Fetch today agent messages from DB]
    FetchMsgs --> Bundle[Bundle into daily progress JSON]
    Bundle --> Railway[RemoteSyncService: POST /daily-progress]
    Railway --> Status{HTTP 2xx?}
    Status -->|Yes| Confirm[Return: published successfully]
    Status -->|No| Err[Return: publish failed + status code]
    Confirm --> AppendCtx[Append to tool result context]
    Err --> AppendCtx
    AppendCtx --> LLM2([LLM re-invoked with publish result])
```

---

### `publish_route_snapshot`

Sends a GeoJSON FeatureCollection of all recorded GPS coordinates to Railway.

```mermaid
graph TD
    LLM([LLM emits publish_route_snapshot]) --> FetchAll[Fetch all locations from DB ordered by recorded_at]
    FetchAll --> GeoJSON[Build GeoJSON FeatureCollection]
    GeoJSON --> Railway[RemoteSyncService: POST /route-snapshot]
    Railway --> Status{HTTP 2xx?}
    Status -->|Yes| Confirm[Return: route snapshot published N points]
    Status -->|No| Err[Return: failed + status]
    Confirm --> AppendCtx[Append to tool result context]
    Err --> AppendCtx
    AppendCtx --> LLM2([LLM re-invoked with result])
```

---

### `upload_image`

Uploads a single remote-candidate photo to Railway as multipart/form-data.

```mermaid
graph TD
    LLM([LLM emits upload_image]) --> ParsePayload[Parse payload: photo_id]
    ParsePayload --> DB[(photos table)]
    DB --> Fetch[Fetch PhotoRecord by id]
    Fetch --> Check{is_remote_candidate AND not uploaded?}
    Check -->|No| Skip[Return: not eligible]
    Check -->|Yes| Policy{daily upload count < max_images_per_day?}
    Policy -->|No| Limit[Return: daily limit reached]
    Policy -->|Yes| Upload[RemoteSyncService: POST /photos/upload multipart]
    Upload --> Status{HTTP 2xx?}
    Status -->|Yes| UpdateDB[Set remote_uploaded=True, remote_url, remote_uploaded_at]
    Status -->|No| Err[Return: upload failed]
    UpdateDB --> Confirm[Return: uploaded successfully + URL]
    Confirm --> AppendCtx[Append to tool result context]
    Err --> AppendCtx
    Skip --> AppendCtx
    Limit --> AppendCtx
    AppendCtx --> LLM2([LLM re-invoked with result])
```

---

### `publish_agent_message`

Saves an agent message to the DB and publishes it to Railway for the expedition website.

```mermaid
graph TD
    LLM([LLM emits publish_agent_message]) --> ParsePayload[Parse payload: content]
    ParsePayload --> DB[(agent_messages table)]
    DB --> Insert[INSERT message record]
    Insert --> Railway[RemoteSyncService: POST /agent-messages]
    Railway --> Status{HTTP 2xx?}
    Status -->|Yes| Confirm[Return: message published]
    Status -->|No| Err[Return: failed + status]
    Confirm --> AppendCtx[Append to tool result context]
    Err --> AppendCtx
    AppendCtx --> LLM2([LLM re-invoked with result])
```

---

### `publish_weather_snapshot`

Publishes the most recent weather snapshot to Railway.

```mermaid
graph TD
    LLM([LLM emits publish_weather_snapshot]) --> DB[(weather_snapshots table)]
    DB --> Fetch[Fetch most recent snapshot]
    Fetch --> Exists{Snapshot found?}
    Exists -->|No| Empty[Return: no weather data available]
    Exists -->|Yes| Railway[RemoteSyncService: POST /weather-snapshots]
    Railway --> Status{HTTP 2xx?}
    Status -->|Yes| Confirm[Return: weather snapshot published]
    Status -->|No| Err[Return: failed + status]
    Confirm --> AppendCtx[Append to tool result context]
    Err --> AppendCtx
    Empty --> AppendCtx
    AppendCtx --> LLM2([LLM re-invoked with result])
```

---

### `send_message` *(final action)*

Sends a message to the user. Always the last action in any chain.

```mermaid
graph TD
    LLM([LLM emits send_message]) --> ParsePayload[Parse payload: content]
    ParsePayload --> StateMsg[state.add_message assistant content]
    StateMsg --> DB[(agent_messages table — persisted)]
    DB --> Display[OutputHandler.display content]
    Display --> Restore[Restore input prompt in terminal]
    Restore --> Release[Release semaphore — idle]
    Release --> End([Loop — wait for next input / tick])
```

---

## Project Structure

```
src/agent/
├── __main__.py              — Entry point: starts CLI + HTTP server + scheduler concurrently
├── config/
│   └── loader.py            — Extended Config: http_server, scheduler, photo_pipeline,
│                              image_preprocessing, weather, remote_sync, runtime sections
├── cli/
│   └── app.py               — CLI with terminal layout, spinner, task output streaming,
│                              input disabled during task_running
├── db/
│   ├── database.py          — aiosqlite connection + init_all_tables()
│   ├── locations_repo.py    — LocationsRepository (locations table)
│   ├── photos_repo.py       — PhotosRepository (photos table)
│   ├── weather_repo.py      — WeatherRepository (weather_snapshots table)
│   ├── tasks_repo.py        — TasksRepository (tasks table — claim / complete / fail)
│   └── messages_repo.py     — MessagesRepository (agent_messages table)
├── http/
│   └── server.py            — asyncio HTTP server — POST /locations → inserts task
├── llm/
│   ├── client.py            — LLMClient Protocol (unchanged)
│   ├── ollama.py            — OllamaClient — text chat + vision (base64 image) via /api/chat
│   └── prompt_builder.py    — Extended: injects location / weather / task context
├── models/
│   ├── actions.py           — 12 action types (11 tools + send_message)
│   ├── photo.py             — PhotoRecord (mirrors photos table)
│   ├── location.py          — LocationRecord
│   ├── task.py              — TaskRecord (type, payload, status — no priority, FIFO)
│   └── state.py             — ConversationState (unchanged)
├── runtime/
│   ├── runtime.py           — Recursive chaining loop + full RESPONSE_FORMAT schema
│   ├── scheduler.py         — 60s tick loop — generates weather tasks, FIFO task execution
│   ├── semaphore.py         — ExecutionSemaphore (idle / user_typing / llm_running / task_running)
│   ├── task_runner.py       — Dispatches 9 task types to services
│   ├── parser.py            — Extended ACTION_REGISTRY (12 actions)
│   └── protocols.py         — OutputHandler Protocol (unchanged)
├── services/
│   ├── photo_service.py     — ImagePreprocessingService + full photo pipeline orchestration
│   ├── weather_service.py   — Open-Meteo API client (httpx)
│   └── remote_sync_service.py — Railway API publishing
└── state/
    ├── store.py             — StateStore Protocol + MemoryStateStore (unchanged)
    └── file_store.py        — FileStateStore (unchanged)

configs/
└── expedition_config.json   — Full expedition agent config

data/
├── photos/
│   ├── inbox/               — Drop new photos here
│   ├── processed/           — Originals moved here after success
│   └── vision_preview/      — Derived preview JPEGs
└── expedition.db            — Single SQLite database


```

## Key Design Decisions

### Recursive tool chaining — LLM loops until `send_message`
The runtime keeps invoking the LLM until it emits `send_message`. After each non-final action, the tool result is appended to the message context as a `tool` role message. `max_chain_depth = 6` prevents infinite loops — at depth 6 a forced `send_message` is injected.

### Semaphore lock is held for the full user interaction cycle
The CLI calls `acquire_typing()` (which acquires the asyncio lock) before showing the `❯` prompt. When Enter is pressed, the state transitions to `llm_running` without releasing the lock. The lock is only released after the agent's final `send_message`. This guarantees the scheduler can never interrupt a conversation mid-reply, and can never fire while the user is typing. The scheduler gets at most one tick opportunity between the end of one reply and the start of the next prompt.

### Input prompt is blocked while a background task runs
When the scheduler picks up a task, it acquires the same lock. The CLI is then waiting at `acquire_typing()` — it cannot show the `❯` prompt until the task finishes. During this wait, the input row shows the spinner and task progress messages stream to the scroll area via `on_task_progress(message)`.

### Task system is DB-backed FIFO, no priority
Tasks persist in the `tasks` table (type, payload JSON, status, created_at). `claim_next()` picks the oldest `pending` task (`ORDER BY created_at ASC`). No priority field — insertion order is the only ordering guarantee. Survives restarts. The LLM (`create_task` action) and the HTTP server both enqueue tasks; neither is special-cased.

### HTTP server is completely independent of the semaphore
The asyncio HTTP server runs as a concurrent task and never acquires the semaphore. GPS coordinates from the iPhone are always stored and `process_location` tasks always queued immediately, regardless of what the CLI or scheduler is doing. The task queue accumulates freely; execution is just deferred until the lock is free.

### HTTP server uses asyncio — no framework dependency
`asyncio.start_server` with a minimal HTTP parser handles `POST /locations`. Single endpoint, no routing needed. Runs as a concurrent asyncio task. No `aiohttp` / `fastapi` dependency added.

### Photo pipeline: preview-first, never touch original
`ImagePreprocessingService` (Pillow) generates a derived JPEG with EXIF orientation corrected and longest side 1280–1600px.

**Vision analysis**: `OllamaClient` sends the preview as base64 to `qwen2.5-vl`. The user message is taken verbatim from `photo_pipeline.vision_prompt` in the config — e.g. *"Describe what you see in detail: the landscape, people, equipment, weather conditions..."*. The model returns a plain-text description. No parsing or structured output needed here.

**Significance scoring**: a second Ollama call (text model `qwen2.5`) receives the description and returns structured JSON `{"significance_score": float}`. Threshold `0.75` gates `is_remote_candidate`. Originals are never modified.

### Remote publishing is policy-controlled
Upload constraints: max 3 images/batch, max 10/day. `RemoteSyncService` tracks daily count in the DB. `publish_daily_progress` bundles locations + weather + messages. `publish_route_snapshot` sends GeoJSON of all coordinates.

## Terminal Layout

```
Row 1..(N-3)  — Scroll area: chat messages, tool logs, task progress, scheduler events
Row N-2       — Rule separator ────────────────────────────────────────────────
Row N-1       — Input ❯  OR  ⠹ task: <name> — <current step>  (during semaphore hold)
Row N         — Status: session | scheduler: next | tasks: N pending | tokens: 1,234
```

-   Scroll region via ANSI `\033[1;{N-3}r` (unchanged from existing CLI)
-   When lock is held by a background task: input row shows spinner (no `❯`), CLI awaits lock release
-   When lock is released by task: CLI immediately acquires for next input, `❯` reappears
-   `on_task_progress(message)` appends task status lines to scroll area in real time during task execution
-   Status bar extended: pending task count

## Configuration

All behavior driven by a single JSON file passed via `--config`:

```json
{
  "agent":        { "name", "greeting", "model", "temperature", "max_tokens" },
  "personality":  { "tone", "style", "formality", "emoji_usage", "prompt" },
  "actions":      { "available": ["...all 12 action definitions..."] },
  "system_prompt": { "template", "dynamic_sections" },
  "runtime":      { "max_chain_depth": 6 },
  "http_server":  { "host": "0.0.0.0", "port": 8080 },
  "scheduler":    { "tick_interval_seconds": 60 },
  "db":           {},
  "photo_pipeline": {
    "significance_threshold": 0.75,
    "vision_prompt": "You are analyzing a photo from an Antarctic expedition. Describe what you see in detail: the landscape, people, equipment, weather conditions, and anything noteworthy. Be specific and objective."
  },
  // Paths and URLs come from environment variables:
  // DB_PATH, PHOTO_INBOX_DIR, PHOTO_PROCESSED_DIR, PHOTO_PREVIEW_DIR
  // OLLAMA_URL, OLLAMA_VISION_MODEL, HTTP_HOST, HTTP_PORT
  // REMOTE_SYNC_BASE_URL, REMOTE_SYNC_API_KEY
  "image_preprocessing": {
    "correct_exif_orientation": true,
    "vision_max_dimension": 1600,
    "vision_min_dimension": 1280,
    "vision_preview_format": "jpeg",
    "vision_preview_quality": 85
  },
  "weather": {
    "provider": "open-meteo",
    "latitude": -62.15,
    "longitude": -58.45,
    "schedule_hours": [6, 12, 18, 0]
  },
  "remote_sync": {
    "base_url": "https://your-railway-app.railway.app",
    "api_key_env": "REMOTE_SYNC_API_KEY",
    "max_images_per_batch": 3,
    "max_images_per_day": 10
  }
}
```

## Commands

```bash
pip install -e ".[dev]"                                                   # install
python -m agent --config configs/expedition_config.json                   # run expedition agent
python -m agent --config configs/expedition_config.json --debug           # debug mode
python -m agent --config configs/example_config.json                      # existing configs unchanged
python -m agent --config configs/expedition_config.json --session <id>    # resume session
```

## Commit History

| #  | Description                                                                  | Status   |
|----|------------------------------------------------------------------------------|----------|
| 1  | Project setup, core models, config loader, schemas                           | Done     |
| 2  | StateStore, OutputHandler, ActionParser, PromptBuilder                       | Done     |
| 3  | Runtime orchestrator                                                         | Done     |
| 4  | CLI interface with test mode                                                 | Done     |
| 5  | OpenRouter LLM client + system prompt engineering + debug mode               | Done     |
| 6  | FileStateStore + enhanced CLI (status bar, spinner, terminal layout)         | Done     |
| 7  | DB layer: aiosqlite + 6 table repos (locations, photos, weather, tasks, messages, sessions) | Done     |
| 8  | Models: LocationRecord, TaskRecord, PhotoRecord                              | Done     |
| 9  | Delete old configs + create expedition_config.json                           | Done     |
| 10 | HTTP server: POST /locations → process_location task                         | Done     |
| 11 | ExecutionSemaphore + Scheduler (60s tick, weather schedule)                  | Done     |
| 12 | Semaphore redesign (lock-based typing, 4 states) + FIFO tasks (no priority) + CLI async input + recursive runtime chaining | Done     |
| 13 | TaskRunner: dispatches all 9 task types + CLI task progress output           | Done     |
| 14 | OllamaClient + .env loading + provider config + DB wiring + scheduler/HTTP/semaphore all wired in __main__.py | Done     |
| 15 | WeatherService: Open-Meteo ECMWF full Antarctic fields + DB persistence + get_weather live fetch | Done     |
| 16 | CLI status bar: location + weather + precipitation + 5min auto-refresh       | Done     |
| 17 | ImagePreprocessingService (Pillow EXIF + resize) + OllamaVisionClient        | Planned  |
| 18 | PhotoService: full pipeline orchestration + significance scoring             | Planned  |
| 19 | RemoteSyncService: Railway API publishing                                    | Planned  |
