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

# Official Signature of the user/department to append to emails
ASSINATURA_EMAIL = os.getenv("ASSINATURA_EMAIL")


# ============================================================================
# Email Channel Selection
# ============================================================================

# Which channel to use for reading emails: "gmail" (API, no MFA) or "owa" (Playwright)
EMAIL_CHANNEL = os.getenv("EMAIL_CHANNEL", "gmail")


# ============================================================================
# Gmail (primary channel — receives forwarded emails from OWA)
# ============================================================================

GMAIL_EMAIL = os.getenv("GMAIL_EMAIL", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")  # App Password for IMAP/SMTP


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
# LLM Provider
# ============================================================================

# API Key for the LLM provider (NEVER hardcode this!)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

# Model to use for classification and response generation
# Easily swappable: change this to any model supported by LiteLLM
LLM_MODEL = os.getenv("LLM_MODEL", "minimax/MiniMax-M2")

# Provider name (matches nanobot config.json providers key)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "minimax")
