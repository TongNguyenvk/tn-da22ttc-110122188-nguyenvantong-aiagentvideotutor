#!/usr/bin/env python3
"""
Regenerate Google Drive OAuth token.

Run this script LOCALLY (not in Docker) when the token expires.
It will open a browser for you to re-authenticate with Google.
The new token will be saved and can then be copied to Docker volumes.

Common reasons for token expiry:
  - Google Cloud project is in "Testing" mode (tokens expire after 7 days)
  - User revoked access in Google Account settings
  - Refresh token not used for 6+ months

To fix permanently: publish your Google Cloud OAuth consent screen
(move from "Testing" to "Production" mode in Google Cloud Console).

Usage:
    python refresh_google_oauth_token.py
"""

import os
import sys
import pickle
import logging
from pathlib import Path

# Setup paths
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("refresh_token")

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Credentials file
CREDENTIALS_FILE = ROOT_DIR / "key" / "client_secret_90225988307-ka4d274h171he15cbvjvktp1n0od82mo.apps.googleusercontent.com.json"
if not CREDENTIALS_FILE.exists():
    CREDENTIALS_FILE = ROOT_DIR / "credentials.json"

# Token file (local)
TOKEN_FILE = ROOT_DIR / "output" / "google_oauth_token.pickle"


def main():
    logger.info("Google Drive OAuth Token Refresh Tool")
    logger.info("=" * 50)

    if not CREDENTIALS_FILE.exists():
        logger.error(
            f"Credentials file not found at {CREDENTIALS_FILE}. "
            f"Download OAuth client credentials from Google Cloud Console."
        )
        sys.exit(1)

    logger.info(f"Credentials file: {CREDENTIALS_FILE}")
    logger.info(f"Token file: {TOKEN_FILE}")

    # Check existing token
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
        logger.info(f"Existing token found (created: {TOKEN_FILE.stat().st_mtime})")
        logger.info(f"  Valid: {creds.valid}")
        logger.info(f"  Expired: {creds.expired}")
        logger.info(f"  Has refresh_token: {bool(creds.refresh_token)}")

        if creds.valid:
            logger.info("Token is still valid. No refresh needed.")
            response = input("Force re-authenticate anyway? (y/N): ")
            if response.lower() != 'y':
                return
            creds = None

        elif creds.expired and creds.refresh_token:
            logger.info("Attempting to refresh token...")
            try:
                creds.refresh(Request())
                logger.info("Token refreshed successfully!")
            except RefreshError as e:
                logger.warning(f"Refresh failed: {e}")
                logger.info("Will re-authenticate from scratch.")
                creds = None
    else:
        logger.info("No existing token found. Will authenticate from scratch.")

    if creds is None:
        # Delete stale token
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            logger.info(f"Deleted stale token: {TOKEN_FILE}")

        logger.info("")
        logger.info("A browser will open for Google OAuth authentication.")
        logger.info("Please log in with: webreelworker@gmail.com")
        logger.info("")

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES,
        )
        creds = flow.run_local_server(port=0)
        logger.info("Authentication successful!")

    # Save token
    TOKEN_FILE.parent.mkdir(exist_ok=True, parents=True)
    with open(TOKEN_FILE, 'wb') as f:
        pickle.dump(creds, f)
    logger.info(f"Token saved to: {TOKEN_FILE}")

    # Verify
    from googleapiclient.discovery import build
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    about = service.about().get(fields='user').execute()
    user_email = about.get('user', {}).get('emailAddress', 'unknown')
    logger.info(f"Authenticated as: {user_email}")

    logger.info("")
    logger.info("=" * 50)
    logger.info("SUCCESS! Token has been refreshed.")
    logger.info("")
    logger.info("If running in Docker, copy the token to the output volume:")
    logger.info(f"  docker cp {TOKEN_FILE} webreel-api:/app/output/google_oauth_token.pickle")
    logger.info("")
    logger.info("TIP: To avoid token expiry every 7 days, publish your")
    logger.info("Google Cloud OAuth consent screen to 'Production' mode.")


if __name__ == "__main__":
    main()
