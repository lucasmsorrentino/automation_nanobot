# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_loop.py -v

# Run a single test function
pytest tests/test_loop.py::test_function_name -v

# Lint
ruff check nanobot/
ruff format nanobot/

# Run the CLI
nanobot onboard          # first-time setup
nanobot agent -m "..."   # send a message
nanobot gateway          # start the gateway server
nanobot status           # show current status

# Run UFPR automation (auto-login + MFA via Telegram)
python -m ufpr_automation               # full pipeline (headless, auto-login)
python -m ufpr_automation --debug       # capture DOM + screenshot
python -m ufpr_automation --headed      # force visible browser
python -m ufpr_automation --perceber-only  # scrape only, no LLM
```

## Architecture

This repo contains two projects:

### nanobot (core framework)

An ultra-lightweight AI agent framework. The agent implements a simple sense → think → act loop.

**Key packages under `nanobot/`:**

- **`agent/`** — The core loop (`loop.py` ~23KB). Receives a message, builds context with system prompt + history, calls the LLM with available tools, executes tool calls, sends response back, persists session. Also contains memory consolidation, subagent spawning, and skills integration.
- **`providers/`** — 20+ LLM providers (OpenRouter, Anthropic, OpenAI, Azure, DeepSeek, Groq, Gemini, Ollama, etc.). Registry-based — no if-elif chains. Adding a provider requires only a `ProviderSpec` and a `ProvidersConfig` field.
- **`channels/`** — 11+ chat platform integrations (Telegram, Discord, Slack, WhatsApp, Feishu, DingTalk, QQ, Matrix, WeChat, Wecom, Email). Base class architecture; community plugins supported. Most use WebSocket/Socket.IO — no public IP required.
- **`tools/`** — Built-in agent tools: shell (with `restrictToWorkspace`), filesystem (path traversal protected), web search (Brave/Tavily/Jina/SearXNG/DuckDuckGo), web fetch (readability), cron (croniter), MCP (Model Context Protocol), spawn (background subagents), message (send to channels).
- **`session/`** — Conversation state grouped by channel+user.
- **`bus/`** — Message routing between channels and agent.
- **`cron/`** — Scheduled task execution.
- **`heartbeat/`** — Proactive periodic task wake-up.
- **`skills/`** — Bundled skills (GitHub, weather, Tmux, memory, summarize, skill-creator, cron).
- **`config/`** — Pydantic-based config schema and loader.
- **`cli/`** — Typer-based CLI (`nanobot` entrypoint).
- **`security/`** — Network access control.

**Data flow:** Channel receives message → Bus routes → Session groups by conversation → Agent loop (`loop.py`) processes → Tools execute → Response sent back via channel.

### ufpr_automation (sub-project)

A specialized deployment automating bureaucratic email processing at UFPR (Universidade Federal do Paraná). Currently in **Marco I (Prototype)** phase (~600 lines).

**Packages under `ufpr_automation/`:**

- **`outlook/`** — Playwright-based scraping of OWA (Outlook Web Access). Includes automated login with credential filling and MFA number-match notification via Telegram Bot.
- **`llm/`** — LLM client for email classification and draft generation (ICL: UFPR regulations in system prompt). Uses LiteLLM (provider-agnostic); currently configured for MiniMax-M2.
- **`config/`** — `.env`-based settings (UTF-8 aware for Windows).
- **`core/`** — Domain model (`EmailData`).
- **`workspace/`** — Nanobot integration files: `SOUL.md` (agent persona + internship regulations knowledge), `AGENTS.md`, `SKILL.md`, `config.json`.

The automation saves responses as drafts — never auto-sends (human-in-the-loop). See `ufpr_automation/ARCHITECTURE.md` for the planned 3-phase maturation roadmap (Marco I → LangGraph → GraphRAG/multi-agent).

## Configuration

- **`pyproject.toml`** — Package metadata, dependencies, Ruff config (line-length=100, target py311). Build backend: hatchling.
- **`.env`** (in `ufpr_automation/`) — OWA credentials, Telegram bot token/chat ID, LLM API keys. See `.env.example`.
- **`docker-compose.yml`** — Two services: `nanobot-gateway` (port 18790, 1 CPU) and `nanobot-cli`.
- **`nanobot/templates/`** — Default config templates copied during `nanobot onboard`.

## Branching

- `main` — Production releases
- `nightly` — Experimental / breaking changes
- Feature branches: `feat/<name>`
- Current branch `feat/marco-i-unified` — Marco I unified implementation with auto-login + MFA via Telegram.
