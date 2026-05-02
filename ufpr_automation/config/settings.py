"""Configuration settings for the UFPR Automation system.

All configurable values are loaded from environment variables (via .env file).
Copy `.env.example` to `.env` and fill in your values.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# .env loading — searches ufpr_automation/ first, then project root
# ---------------------------------------------------------------------------
_PACKAGE_DIR = Path(__file__).resolve().parent.parent  # ufpr_automation/
_ENV_FILE = _PACKAGE_DIR / ".env"
if not _ENV_FILE.exists():
    _ENV_FILE = _PACKAGE_DIR.parent / ".env"  # project root
load_dotenv(_ENV_FILE, override=False, encoding="utf-8")


# ============================================================================
# Paths
# ============================================================================

# ufpr_automation package root
PACKAGE_ROOT = _PACKAGE_DIR

# Project root (nanobot repo root)
PROJECT_ROOT = _PACKAGE_DIR.parent

# Directory where browser session state (cookies, storage) is persisted
SESSION_DIR = _PACKAGE_DIR / "session_data"

# File that stores the saved browser context (cookies + local storage)
SESSION_STATE_FILE = SESSION_DIR / "state.json"

# Debug output directory
DEBUG_OUTPUT_DIR = _PACKAGE_DIR / "debug_output"

# Directory where downloaded email attachments are stored
ATTACHMENTS_DIR = Path(os.getenv("ATTACHMENTS_DIR", str(_PACKAGE_DIR / "attachments_data")))

# Max attachment size to download (in MB)
ATTACHMENT_MAX_SIZE_MB = int(os.getenv("ATTACHMENT_MAX_SIZE_MB", "25"))


# ============================================================================
# RAG — Vector store and documents directories
# ============================================================================

# Override to share the store via network/cloud (e.g. Google Drive, NAS)
RAG_STORE_DIR = Path(os.getenv("RAG_STORE_DIR", str(_PACKAGE_DIR / "rag" / "store")))
RAG_DOCS_DIR = Path(os.getenv("RAG_DOCS_DIR", str(_PACKAGE_DIR / "docs")))


# ============================================================================
# Feedback / Procedures — human corrections + learning data
# Override to share across machines (e.g. Google Drive, NAS).
# Default keeps everything local to the package.
# ============================================================================

FEEDBACK_DATA_DIR = Path(os.getenv("FEEDBACK_DATA_DIR", str(_PACKAGE_DIR / "feedback_data")))
PROCEDURES_DATA_DIR = Path(os.getenv("PROCEDURES_DATA_DIR", str(_PACKAGE_DIR / "procedures_data")))


# ============================================================================
# Outlook Web Access (OWA)
# ============================================================================

# Credentials for automated login (loaded from .env — NEVER hardcode)
OWA_EMAIL = os.getenv("OWA_EMAIL", "")
OWA_PASSWORD = os.getenv("OWA_PASSWORD", "")

# Base URL for UFPR's Outlook Web Access
OWA_URL = os.getenv("OWA_URL", "https://outlook.office365.com/mail/")

# URL that confirms successful login (inbox view)
OWA_INBOX_URL = os.getenv(
    "OWA_INBOX_URL",
    "https://outlook.cloud.microsoft/mail/?msalAuthRedirect=true",
)


# ============================================================================
# Browser Settings
# ============================================================================

# Default timeout for page navigations and element waits (in milliseconds)
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "60000"))

# Timeout for waiting for manual login (5 minutes in ms)
LOGIN_TIMEOUT_MS = int(os.getenv("LOGIN_TIMEOUT_MS", "300000"))

# User agent to mimic a real browser session
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Viewport size for the browser window
VIEWPORT = {"width": 1366, "height": 768}


# ============================================================================
# Institutional Info
# ============================================================================

# Official Signature of the user/department to append to emails.
# Stored as a single-line value in .env with literal "\n" — this block
# decodes them to real line breaks so the signature renders correctly.
_assinatura_raw = os.getenv("ASSINATURA_EMAIL")
ASSINATURA_EMAIL = _assinatura_raw.replace("\\n", "\n") if _assinatura_raw else None

# Default Cc applied to every generated email draft (empty = disabled).
# Intended for the shared secretaria mailbox so every response is archived
# in the institutional inbox automatically.
EMAIL_CC_DEFAULT = os.getenv("EMAIL_CC_DEFAULT", "").strip()

# Institutional email of the human coordinator. When a Gmail thread's most
# recent message is from this address, the pipeline skips drafting (the
# human already handled it) and routes the thread into the learning corpus.
INSTITUTIONAL_EMAIL = os.getenv("INSTITUTIONAL_EMAIL", "design.grafico@ufpr.br").strip().lower()

# Gmail label used as the learning corpus for future template mining.
# Nested paths use "/" (Gmail treats labels as IMAP folders). Empty string
# disables corpus capture entirely.
GMAIL_LEARNING_LABEL = os.getenv(
    "GMAIL_LEARNING_LABEL", "aprendizado/interacoes-secretaria-humano"
).strip()


# ============================================================================
# Email Channel Selection
# ============================================================================

# Which channel to use for reading emails: "gmail" (API, no MFA) or "owa" (Playwright)
EMAIL_CHANNEL = os.getenv("EMAIL_CHANNEL", "gmail")


# ============================================================================
# Gmail (primary channel — receives forwarded emails from OWA)
# ============================================================================

GMAIL_EMAIL = os.getenv("GMAIL_EMAIL", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")  # IMAP credential


# ============================================================================
# Telegram (MFA notification for OWA login)
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================================
# SIGA (Sistema de Gestão Acadêmica)
# ============================================================================

SIGA_URL = os.getenv("SIGA_URL", "https://www.prppg.ufpr.br/siga/")
SIGA_USERNAME = os.getenv("SIGA_USERNAME", "")
SIGA_PASSWORD = os.getenv("SIGA_PASSWORD", "")


# ============================================================================
# SEI (Sistema Eletrônico de Informações)
# ============================================================================

SEI_URL = os.getenv("SEI_URL", "https://sei.ufpr.br/")
SEI_USERNAME = os.getenv("SEI_USERNAME", "")
SEI_PASSWORD = os.getenv("SEI_PASSWORD", "")


# ============================================================================
# UFPR Aberta (Moodle — cursos institucionais, login independente)
# ============================================================================

UFPR_ABERTA_URL = os.getenv("UFPR_ABERTA_URL", "https://ufpraberta.ufpr.br")
# Note: the .env key is LOGING_UFPR_ABERTA (intentional — matches user's file).
UFPR_ABERTA_USERNAME = os.getenv("LOGING_UFPR_ABERTA", "").strip()
UFPR_ABERTA_PASSWORD = os.getenv("SENHA_UFPR_ABERTA", "").strip()


# ============================================================================
# Neo4j (GraphRAG — Marco III)
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


# ============================================================================
# Scheduler
# ============================================================================

# Comma-separated hours (24h format) when the pipeline runs automatically
SCHEDULE_HOURS = os.getenv("SCHEDULE_HOURS", "8,13,17")

# Timezone for scheduling
SCHEDULE_TZ = os.getenv("SCHEDULE_TZ", "America/Sao_Paulo")


# ============================================================================
# LLM Provider
# ============================================================================

# API Key for the LLM provider (NEVER hardcode this!)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

# Default model (used when cascading models are not configured)
# Easily swappable: change this to any model supported by LiteLLM
LLM_MODEL = os.getenv("LLM_MODEL", "minimax/MiniMax-M2")

# Provider name (matches nanobot config.json providers key)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "minimax")


# ============================================================================
# Model Cascading (Marco III) — route tasks to optimal models
# ============================================================================

# Classification model: cheaper/local model for categorization (e.g. ollama/qwen3:8b)
# Empty = use LLM_MODEL for everything (no cascading)
LLM_CLASSIFY_MODEL = os.getenv("LLM_CLASSIFY_MODEL", "")

# Drafting model: higher-quality model for response generation
# Empty = use LLM_MODEL
LLM_DRAFT_MODEL = os.getenv("LLM_DRAFT_MODEL", "")

# Fallback model: used when primary model fails (timeout, rate limit, down)
# Empty = no fallback (error propagates)
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")

# Max retries before falling back to the next model
LLM_CASCADE_RETRIES = int(os.getenv("LLM_CASCADE_RETRIES", "2"))

# Timeout per LLM call in seconds (local models may need longer)
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))


# ============================================================================
# DSPy — prompt optimization (Marco II)
# ============================================================================
USE_DSPY = os.getenv("USE_DSPY", "auto").lower()
# "auto" = use DSPy only if dspy_modules/optimized/gepa_optimized.json exists
# "1" / "true" / "on" = force DSPy (raises if no compiled file)
# "0" / "false" / "off" = force litellm path (skip DSPy entirely)


# ============================================================================
# SEI write operations (Marco III) — attach + draft only, NO sign/send
# ============================================================================
SEI_WRITE_ARTIFACTS_DIR = Path(
    os.getenv("SEI_WRITE_ARTIFACTS_DIR", str(_PACKAGE_DIR / "procedures_data" / "sei_writes"))
)

# SEI write mode — controls whether SEIWriter actually clicks in SEI.
#   live (default)   — full Playwright flow. Sprint 3 validado 2026-04-16
#                      (run_id c0357e8dd8f2, processo 23075.022027/2026-22)
#                      e ativo em produção desde 2026-04-23. Fleet ainda
#                      gateia via `agir_estagios` (checker registry) — SEIWriter
#                      só roda quando todos os checks passam.
#   dry_run          — apenas loga intenção + screenshots, NÃO clica em
#                      nada. Usar pra smokes offline, CI, ou quando os
#                      seletores precisarem ser re-capturados.
SEI_WRITE_MODE = os.getenv("SEI_WRITE_MODE", "live").lower()


# ============================================================================
# LangGraph Fleet — sub-agent concurrency
# ============================================================================
# Caps how many Fleet sub-agents (``process_one_email`` bodies) execute the
# heavy RAG + classify work at the same time. LangGraph's Send API fan-out
# dispatches one sub-agent per Tier 1 email in its own thread; without this
# cap, N emails would hit the LLM / RAG stack with N-wide parallelism and
# risk OOM (see ``ufpr_automation/TASKS.md`` "Fleet OOM"). The semaphore is
# created in :mod:`ufpr_automation.graph.fleet`; sub-agents beyond the limit
# block inside ``with _SUBAGENT_SEMAPHORE:`` until a slot frees up.
#
# Default 2 is tuned for the current dev host (~16 GB RAM). Raise this when
# the box has more memory/CPU; lower to 1 to serialize completely.
FLEET_MAX_CONCURRENT_SUBAGENTS = int(os.getenv("FLEET_MAX_CONCURRENT_SUBAGENTS", "2"))


# ============================================================================
# AFlow — topology evaluator (Marco III)
# ============================================================================
AFLOW_TOPOLOGY = os.getenv("AFLOW_TOPOLOGY", "fleet").lower()
# Valid: "fleet" (default — Wave 2 parallel sub-agents), "baseline" (legacy
# sequential), "skip_rag_high_tier0", "no_self_refine", "fleet_no_siga"
AFLOW_METRIC = os.getenv("AFLOW_METRIC", "composite").lower()
AFLOW_EVAL_LIMIT = int(os.getenv("AFLOW_EVAL_LIMIT", "20"))
