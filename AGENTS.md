# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build / Run / Test Commands

```bash
# Server (Python 3.11+ required)
make install          # venv + dependencies
make run              # uvicorn --reload on :8080
curl localhost:8080/health

# iOS
# Open ios/LiteAilohaApp.xcodeproj in Xcode 16+.
# Mock mode (no server needed): AnalysisService.useMock = true
# Real server: set useMock=false + update endpoint URL
```

## Architecture

**Multimodal-model-driven: chat screenshot → structured conversation → action cards.**

```
iOS photo picker → resize/compress image → POST base64 image + user_context to server
→ VISION_MODEL structures conversation (participants, messages, timeline)
→ LLM_MODEL powers subagents for domain extraction
→ SSE stream back: event:struct → event:card × N → event:insight → event:done
→ iOS renders ActionCards → user confirm/cancel → POST /api/v1/actions/{id}/*
```

### Multi-Model Configuration

Two independently configurable models (`.env` / `config.py`):

| Config | Role | Requires Vision |
|---|---|---|
| `VISION_MODEL` / `VISION_API_KEY` / `VISION_BASE_URL` | Coordinator: see screenshot, structure conversation | **Yes** |
| `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | Subagents: extract meetings/contacts/reminders from structured text | No |

Any OpenAI-compatible API works. Both can point to the same model (e.g. GPT-4o for both roles).

### Data Flow & Persistence

Every analysis session produces data visible in **three places**:

1. **SSE stream** (real-time): `event:struct` → `event:card` × N → `event:insight` → `event:done`
2. **SQLite `analyze_sessions` table** (persistent): session_id, structured_conversation JSON, cards JSON, insight, created_at
3. **`GET /api/v1/sessions/{id}`** (retrievable): full session JSON for post-hoc quality evaluation

### iOS Layer (SwiftUI + MVVM)

- **`AnalysisViewModel`** is the central state machine: pick image → send to server → consume SSE. Owns `@Published` cards, insight, structure, toast state.
- **`AnalysisService`** wraps an `AsyncThrowingStream<StreamEvent, Error>` for SSE. `useMock = true` for offline dev.
- **`ImageProcessor`** resizes to max 1024px before upload (bandwidth optimization).
- **Card types** are canonical across the stack: `create_meeting`, `create_contact`, `update_contact`, `create_reminder`.
- **Core Data** stores only confirmed cards (`SavedCard` entity).

### Server Layer (FastAPI + DeepAgents)

- **`server/app/main.py`** — FastAPI entry. CORS wide-open for dev. Lifespan hook init's SQLite schema.
- Endpoints: `POST /api/v1/analyze` (SSE), `POST /api/v1/actions/{id}/confirm|cancel`, `GET /api/v1/sessions/{id}`, `GET /health`.
- **SSE protocol**: named events (`event: struct|card|insight|error|done`) with `id:` field. `data:` line is always JSON.

### Agent Module (`server/app/agent/`)

Dual-model architecture built on `deepagents`:

- **`deep_agent.py`** — `LiteAilohaAgent` class. Two LLM instances: `_vision_llm` (VISION_MODEL, for Coordinator) and `_text_llm` (LLM_MODEL, for subagents). Coordinator prompts include the screenshot as a multimodal message.
- **`subagents.py`** — Three subagents (Meeting/Contact/Reminder) use `_text_llm`. They receive structured text, never images.
- **`prompts.py`** — Five prompts: `COORDINATOR_PROMPT` (vision: structure conversation, then delegate), plus 3 subagent prompts + structurer prompt.
- **`tools/`** — Domain-split. `structure.py` calls VISION_MODEL to parse chat screenshots into structured JSON. `meeting.py`, `contact.py`, `reminder.py`, `insight.py` for domain extraction.

### Services & Storage (`server/app/services/`, `server/app/storage/`)

- Services are **MVP mocks** (calendar, contact, insight).
- **`storage/database.py`** — SQLite via aiosqlite (WAL mode). Tables: `contacts`, `confirmed_actions`, `analyze_sessions`. See [Comment Conventions] for field documentation requirements.
- **`storage/checkpoint.py`** — LangGraph SqliteSaver.

## Verification

**Every code generation must be followed by CLI verification. A task is NOT complete until verification passes with zero errors and zero warnings.**

### Post-Generation Checks

#### iOS — after any `.swift` file change

```bash
# 获取已启动的模拟器 ID
SIM_ID=$(xcrun simctl list devices available | grep -m1 Booted | grep -oE '[A-F0-9-]{36}')

# 编译检查（零错误零警告）
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project ios/LiteAilohaApp.xcodeproj \
  -scheme LiteAilohaApp \
  -destination "platform=iOS Simulator,id=$SIM_ID" \
  build 2>&1 | grep -E "error:|warning:"
# 无输出 = 通过。有输出 = 必须修复。
```

#### Server — after any `.py` file change

```bash
# Import 检查（无 ImportError / ModuleNotFoundError）
cd server && ../.venv/bin/python -c "from app.main import app; print('OK')"

# Lint 检查
cd server && ../.venv/bin/ruff check app/
```

### Failure Protocol

1. 先看 CLI 输出的错误信息
2. 定位文件和行号
3. 修复代码
4. 重新运行验证命令
5. 验证通过才算该任务完成

### Pre-Commit Hook

安装方式：将以下脚本保存为 `.git/hooks/pre-commit` 并 `chmod +x`。

```bash
#!/bin/bash
set -e
echo "=== Server: import check ==="
cd server && ../.venv/bin/python -c "from app.main import app; print('OK')"
echo "=== Server: lint ==="
cd server && ../.venv/bin/ruff check app/
echo "=== iOS: build ==="
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
SIM_ID=$(xcrun simctl list devices available | grep -m1 Booted | grep -oE '[A-F0-9-]{36}')
if [ -n "$SIM_ID" ]; then
    xcodebuild -project ios/LiteAilohaApp.xcodeproj -scheme LiteAilohaApp \
      -destination "platform=iOS Simulator,id=$SIM_ID" build 2>&1 | grep -E "error:|warning:" && exit 1 || true
fi
echo "=== All checks passed ==="
```

## Key Conventions

- **Card types MUST be consistent** across Swift and Python. The four canonical types are `create_meeting`, `create_contact`, `update_contact`, `create_reminder`. Never introduce a new type without updating both `Models.swift` + `schemas/response.py` + `tools/__init__.py` + all prompt files.
- **SSE protocol**: every event must have an `event:` line, an `id:` line (monotonically increasing integer), and a `data:` line with valid JSON. The `done` event signals stream end.
- **Endpoint paths**: the server uses `/api/v1/` prefix. The iOS client `endpoint` URL must match exactly.
- **Mock-first on iOS**: `AnalysisService.useMock = true` works without a running server. Mock cards exercise all 4 action types.
- **Python 3.11+** required (uses `match`/`case`).

## Comment Conventions

Comments must be written in Chinese, targeting the following areas with **maximum detail**:

### 1. SSE Streaming Pipeline — every layer must document what events flow through

- **`api/analyze.py`**: document the SSE event sequence (struct → card → insight → done), what triggers each event, and what happens on error
- **`agent/deep_agent.py`**: document how `on_tool_end` events from subagents are intercepted, parsed, and mapped to SSE event types. Explain the `_parse_stream_event()` event→output mapping
- **iOS `AnalysisService.swift`**: document the SSE line-by-line parsing logic (event: line → data: line), protocol compatibility modes, and the `emit()` dispatch table

### 2. Data Persistence — every table and write path must have field-level comments

- **`storage/database.py`**: every column in CREATE TABLE must have an inline comment explaining what data it stores, its format (JSON/string/timestamp), and when it's written
- **`api/analyze.py`**: document WHERE session data is written during the SSE streaming lifecycle (struct → cards → insight)
- **`api/sessions.py`**: document what the GET endpoint returns and how to interpret each field for quality evaluation
- **iOS `Persistence.swift`**: document what `SavedCard` stores and when saves happen (confirm flow)

### 3. Agent Tool I/O — every tool must document its data contract

- **`tools/structure.py`**: document the input (screenshot base64), the model call, and the output JSON schema (`{participants, messages[{time, speaker, content}]}`)
- **`tools/meeting.py`, `contact.py`, `reminder.py`, `insight.py`**: document each tool's args, return JSON structure, and which subagent calls it
- **`tools/__init__.py`**: document the tool grouping rationale (why each tool goes to which subagent)

### 4. Model Configuration — document which model does what

- **`config.py`**: document each VISION_* and LLM_* env var with its role (Coordinator vs Subagent) and whether vision support is required
- **`deep_agent.py`**: document the two LLM instances, why they're separate, and the fallback behavior when only one model is configured
