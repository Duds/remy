#!/usr/bin/env python3
"""
Google authentication setup for remy.

PREREQUISITE (both options need this):
  1. https://console.cloud.google.com/ → select/create a project
  2. APIs & Services → Enable:
       • Google Calendar API
       • Gmail API
       • Google Docs API
  3. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
       Application type: Desktop app
       Name: remy (or anything)
  4. Download the JSON file → save as  data/client_secrets.json

─────────────────────────────────────────────────────────
OPTION A  gcloud + client_secrets.json  (recommended)
─────────────────────────────────────────────────────────
  This script detects data/client_secrets.json and runs the gcloud
  command for you.  You approve access in the browser — done.
  Creates: ~/.config/gcloud/application_default_credentials.json

─────────────────────────────────────────────────────────
OPTION B  Python OAuth flow  (manual client ID + secret)
─────────────────────────────────────────────────────────
  From the downloaded JSON, copy the client_id and client_secret into .env:
      GOOGLE_CLIENT_ID=<value>
      GOOGLE_CLIENT_SECRET=<value>
  Then run this script — it opens a browser and saves data/google_token.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

CLIENT_SECRETS = _ROOT / "data" / "client_secrets.json"
TOKEN_FILE = _ROOT / "data" / "google_token.json"

from remy.google.auth import SCOPES, _GCLOUD_SCOPES, GCLOUD_ADC_COMMAND


# ── helpers ───────────────────────────────────────────────────────────────────


def _check_adc() -> bool:
    try:
        from remy.google.auth import _try_adc
        _try_adc()
        return True
    except Exception:
        return False


def _find_gcloud() -> str | None:
    """Return path to a working gcloud binary, or None."""
    for candidate in [
        "/opt/homebrew/bin/gcloud",
        "/usr/local/bin/gcloud",
        "gcloud",
    ]:
        try:
            result = subprocess.run(
                [candidate, "version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            pass
    return None


# ── Option A: gcloud ──────────────────────────────────────────────────────────


def run_gcloud_adc(gcloud: str) -> bool:
    """Run gcloud auth application-default login with client_secrets.json."""
    print(f"\nRunning gcloud auth application-default login")
    print(f"  --client-id-file={CLIENT_SECRETS}")
    print(f"  --scopes=<calendar, gmail, docs, openid>\n")
    print("A browser window will open — log in with your Google account and approve access.\n")

    cmd = [
        gcloud,
        "auth", "application-default", "login",
        f"--client-id-file={CLIENT_SECRETS}",
        f"--scopes={','.join(_GCLOUD_SCOPES)}",
    ]
    result = subprocess.run(cmd)
    return result.returncode == 0


# ── Option B: Python OAuth flow ───────────────────────────────────────────────


def run_python_oauth(client_id: str, client_secret: str) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("A browser window will open — log in with your Google account and approve access.")
    print(f"Token will be saved to: {TOKEN_FILE}\n")

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token saved to {TOKEN_FILE}")


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("\n🔑 remy Google authentication setup\n")

    # Already authenticated?
    if _check_adc():
        print("✅ Already authenticated via Application Default Credentials.")
        print()
        print("Run: python scripts/test_google_integration.py  to verify all APIs.")
        return

    if TOKEN_FILE.exists():
        try:
            from remy.google.auth import get_credentials
            get_credentials(str(TOKEN_FILE))
            print(f"✅ Already authenticated via token file: {TOKEN_FILE}")
            print("Run: python scripts/test_google_integration.py  to verify all APIs.")
            return
        except Exception:
            print(f"⚠️  Token file exists but is invalid — re-authenticating.\n")

    # ── OPTION A: client_secrets.json + gcloud ────────────────────────────────
    if CLIENT_SECRETS.exists():
        print(f"Found: {CLIENT_SECRETS}")
        gcloud = _find_gcloud()
        if gcloud:
            print(f"Found: {gcloud}")
            print("\n→ Using Option A: gcloud + client_secrets.json\n")
            if run_gcloud_adc(gcloud):
                print("\n✅ Authentication successful!")
                print("Run: python scripts/test_google_integration.py  to verify all APIs.")
            else:
                print("\n❌ gcloud authentication failed.")
                print(f"Try Option B: add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env")
                print("and re-run this script.")
            return
        else:
            print("⚠️  gcloud not found — falling back to Python OAuth flow.")

    # ── OPTION B: client ID + secret from .env ────────────────────────────────
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

    if client_id and client_secret:
        print("→ Using Option B: Python OAuth flow (client ID from .env)\n")
        run_python_oauth(client_id, client_secret)
        print("\nRun: python scripts/test_google_integration.py  to verify all APIs.")
        return

    # ── Neither option available — print instructions ─────────────────────────
    print("Neither Option A nor Option B is set up yet.\n")
    print("STEP 1 — Create OAuth 2.0 credentials (required for both options):")
    print("  1. https://console.cloud.google.com/")
    print("  2. Enable APIs: Google Calendar, Gmail, Google Docs")
    print("  3. Credentials → Create → OAuth 2.0 Client ID → Desktop app")
    print("  4. Download the JSON → save as  data/client_secrets.json")
    print()
    print("STEP 2 — Authenticate (choose one):")
    print()
    print("  Option A (gcloud — recommended):")
    print(f"    Place data/client_secrets.json, then re-run this script.")
    print(f"    Or manually: {GCLOUD_ADC_COMMAND}")
    print()
    print("  Option B (Python flow):")
    print("    Add to .env:  GOOGLE_CLIENT_ID=<id>  GOOGLE_CLIENT_SECRET=<secret>")
    print("    Then re-run this script.")


if __name__ == "__main__":
    main()
