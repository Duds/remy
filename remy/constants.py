"""
Shared constants for remy.

Centralises values that are used across multiple modules to avoid duplication
and ensure consistency.
"""

from pathlib import Path

# ── Working messages (shown while processing) ───────────────────────────────────
WORKING_MESSAGES = [
    "Reticulating splines…",
    "Homologating girdles…",
    "Initializing neural pathways…",
    "Consulting the archives…",
    "Synthesizing creative juices…",
    "Parsing the universe…",
    "Herding digital cats…",
    "Buffing the bits…",
    "Aligning the planets…",
    "Calculating the meaning of life…",
    "Polishing the protocols…",
    "Twiddling virtual thumbs…",
    "Brewing digital coffee…",
    "Charging flux capacitors…",
    "Optimizing the optimism…",
    "Rerouting power to thinking…",
]


# ── Standardised error messages ─────────────────────────────────────────────────
ERROR_MESSAGES = {
    "rate_limited": "You're sending messages too quickly. Please wait a moment.",
    "service_unavailable": "The service is temporarily unavailable. Please try again later.",
    "auth_failed": "Authentication failed. Please check your credentials.",
    "not_authorised": "You're not authorised to use this bot.",
    "empty_message": "Please provide a message.",
    "message_too_long": "Your message is too long. Please shorten it.",
    "command_too_long": "Command is too long.",
    "invalid_path": "Invalid file path.",
    "path_not_allowed": "Access to this path is not allowed.",
    "file_not_found": "File not found.",
    "google_not_configured": "Google Workspace is not configured. Run setup_google_auth.py first.",
    "circuit_open": "This service is temporarily unavailable due to repeated failures. Please try again later.",
    "timeout": "The operation timed out. Please try again.",
    "cancelled": "Operation cancelled.",
}


# ── Telegram message limits ─────────────────────────────────────────────────────
TELEGRAM_MAX_MESSAGE_LENGTH = 4000
TELEGRAM_MAX_CAPTION_LENGTH = 1024


# ── Tool turn prefix (for conversation storage) ─────────────────────────────────
TOOL_TURN_PREFIX = "__TOOL_TURN__:"


# ── Keywords for context detection ──────────────────────────────────────────────
SHOPPING_KEYWORDS = frozenset({
    "grocery", "groceries", "shopping", "buy", "purchase", "shop",
    "supermarket", "store", "woolworths", "coles", "aldi",
})

DEADLINE_KEYWORDS = frozenset({
    "deadline", "due", "by tomorrow", "by next", "urgent", "asap",
    "time-sensitive", "before", "until",
})


# ── File extensions for indexing ────────────────────────────────────────────────
DEFAULT_INDEX_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
    ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh",
    ".sql", ".graphql",
    ".go", ".rs", ".java", ".kt", ".swift",
    ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".pl",
    ".toml", ".ini", ".cfg", ".conf",
})


# ── Sensitive file patterns (never indexed or read) ─────────────────────────────
SENSITIVE_FILE_NAMES = frozenset({
    ".env",
    ".git",
    ".aws",
    ".ssh",
    ".gnupg",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "client_secrets.json",
    "credentials.json",
    "google_token.json",
    "application_default_credentials.json",
    "service_account.json",
})

SENSITIVE_FILE_PREFIXES = (".env",)
SENSITIVE_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".cer", ".crt", ".jks")
