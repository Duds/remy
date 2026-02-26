"""
Google credential management.

Both authentication paths require OAuth 2.0 client credentials from Google Cloud Console:

  1. Go to https://console.cloud.google.com/
  2. Create/select a project
  3. Enable: Google Calendar API, Gmail API, Google Docs API, People API
  4. Credentials → Create → OAuth 2.0 Client ID → Application type: Desktop app
  5. Download the JSON file → save as  data/client_secrets.json

Then authenticate using ONE of these options:

──────────────────────────────────────────────────────────────────────────
OPTION A: gcloud + client_secrets.json  (recommended — one command)
──────────────────────────────────────────────────────────────────────────
  gcloud auth application-default login \\
      --client-id-file=data/client_secrets.json \\
      --scopes=openid,https://www.googleapis.com/auth/userinfo.email,\\
               https://www.googleapis.com/auth/cloud-platform,\\
               https://www.googleapis.com/auth/calendar,\\
               https://www.googleapis.com/auth/gmail.modify,\\
               https://www.googleapis.com/auth/documents,\\
               https://www.googleapis.com/auth/contacts

  Creates ~/.config/gcloud/application_default_credentials.json.
  drbot picks this up automatically via google.auth.default().

──────────────────────────────────────────────────────────────────────────
OPTION B: Python OAuth flow  (fallback / alternative)
──────────────────────────────────────────────────────────────────────────
  Add to .env:
      GOOGLE_CLIENT_ID=<from the downloaded JSON>
      GOOGLE_CLIENT_SECRET=<from the downloaded JSON>

  Then run:  python scripts/setup_google_auth.py
  Creates data/google_token.json.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/contacts",
]

# All scopes needed by gcloud ADC (cloud-platform is mandatory for ADC)
_GCLOUD_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
] + SCOPES

# Canonical gcloud command (requires data/client_secrets.json)
GCLOUD_ADC_COMMAND = (
    "gcloud auth application-default login \\\n"
    "    --client-id-file=data/client_secrets.json \\\n"
    "    --scopes=" + ",".join(_GCLOUD_SCOPES)
)


def _try_adc():
    """
    Attempt Application Default Credentials
    (written by 'gcloud auth application-default login').
    Returns credentials or raises.
    """
    from google.auth import default as google_auth_default
    from google.auth.transport.requests import Request

    # google.auth.default() uses the ADC file; pass our scopes so the
    # returned credentials are scoped correctly.
    creds, _ = google_auth_default(scopes=SCOPES)

    if hasattr(creds, "expired") and creds.expired and hasattr(creds, "refresh"):
        creds.refresh(Request())
        logger.debug("ADC credentials refreshed")

    return creds


def get_credentials(token_file: str | None = None):
    """
    Return valid Google credentials.

    Tries ADC (gcloud application-default) first.
    Falls back to the token file produced by scripts/setup_google_auth.py.
    Raises if neither is available.
    """
    # 1. Application Default Credentials
    try:
        creds = _try_adc()
        logger.debug("Using Google Application Default Credentials")
        return creds
    except Exception as adc_err:
        logger.debug("ADC not available (%s), trying token file", adc_err)

    # 2. Token file (scripts/setup_google_auth.py)
    if token_file is None:
        raise RuntimeError(
            "Google not authenticated.\n"
            f"Run:  {GCLOUD_ADC_COMMAND}\n"
            "Or:   python scripts/setup_google_auth.py"
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = Path(token_file)
    if not token_path.exists():
        raise FileNotFoundError(
            f"Token file not found: {token_file}\n"
            "Authenticate with:\n"
            f"  Option A (gcloud): {GCLOUD_ADC_COMMAND}\n"
            "  Option B (script): python scripts/setup_google_auth.py"
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.debug("Token refreshed and saved to %s", token_file)

    return creds


def is_configured(token_file: str | None = None) -> bool:
    """Return True if Google credentials are available and usable."""
    try:
        get_credentials(token_file)
        return True
    except Exception:
        return False
