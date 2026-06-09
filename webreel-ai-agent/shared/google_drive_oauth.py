"""
Google Drive API with OAuth 2.0 (user authentication).
This uploads directly to the user's Drive, not Service Account.

Tokens are provisioned out-of-band by an admin (via the admin UI or a
helper script), never via in-container browser flow. Workers and the API
read the same pickle file from the shared output volume; if it's missing
or unrecoverable, we fail FAST with a clear message instead of trying
`run_local_server` which calls `webbrowser.open()` and crashes in
container environments with "could not locate runnable browser".
"""

import os
import pickle
import logging
import time
from pathlib import Path

# NOTE: the heavy `googleapiclient` import is deferred to inside
# get_drive_service_oauth / upload_to_gdrive_oauth so that the API
# container — which only calls get_token_status / save_uploaded_token —
# doesn't need google-api-python-client installed.
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

logger = logging.getLogger("google_drive_oauth")


class GoogleOAuthNotConfigured(RuntimeError):
    """Raised when no valid OAuth token is available and we can't refresh.

    The error message tells the operator exactly how to fix it: upload a
    fresh token via the admin UI. We do NOT attempt an interactive browser
    flow inside the container — that's what was causing the
    `webbrowser.Error: could not locate runnable browser` crash.
    """


WORKER_DIR = Path(__file__).parent.parent
# Try multiple locations for credentials file
CREDENTIALS_FILE = WORKER_DIR / "key" / "client_secret_90225988307-ka4d274h171he15cbvjvktp1n0od82mo.apps.googleusercontent.com.json"
if not CREDENTIALS_FILE.exists():
    CREDENTIALS_FILE = WORKER_DIR.parent / "key" / "client_secret_90225988307-ka4d274h171he15cbvjvktp1n0od82mo.apps.googleusercontent.com.json"

# Token file in mounted output directory (shared between API + workers)
TOKEN_FILE = Path("/app/output/google_oauth_token.pickle")
if not TOKEN_FILE.parent.exists():
    TOKEN_FILE = WORKER_DIR / "output" / "google_oauth_token.pickle"

SCOPES = ['https://www.googleapis.com/auth/drive.file']


def _load_token():
    """Load the pickled credentials object from disk, or None if missing."""
    if not TOKEN_FILE.exists():
        return None
    try:
        with open(TOKEN_FILE, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.error(f"Could not unpickle token at {TOKEN_FILE}: {e}")
        return None


def _save_token(creds) -> None:
    """Persist refreshed credentials back to the shared token file."""
    TOKEN_FILE.parent.mkdir(exist_ok=True, parents=True)
    with open(TOKEN_FILE, 'wb') as f:
        pickle.dump(creds, f)
    logger.info(f"OAuth token saved to {TOKEN_FILE}")


def get_token_status() -> dict:
    """Inspect the current token without raising.

    Returns a dict suitable for the admin UI status card:
      - exists: bool
      - valid: bool (loadable + not expired or refreshable)
      - expired: bool
      - has_refresh_token: bool
      - scopes: list[str]
      - expiry: ISO timestamp or None
      - token_path: str (where the worker will look for it)
      - credentials_file_exists: bool
      - warning_level: "ok" | "warning" | "critical" | "missing"
    """
    info: dict = {
        "exists": False,
        "valid": False,
        "expired": False,
        "has_refresh_token": False,
        "scopes": [],
        "expiry": None,
        "token_path": str(TOKEN_FILE),
        "credentials_file_exists": CREDENTIALS_FILE.exists(),
        "credentials_path": str(CREDENTIALS_FILE),
        "warning_level": "missing",
    }

    creds = _load_token()
    if creds is None:
        return info

    info["exists"] = True
    info["scopes"] = list(getattr(creds, "scopes", []) or [])
    info["has_refresh_token"] = bool(getattr(creds, "refresh_token", None))
    info["expired"] = bool(getattr(creds, "expired", False))
    info["valid"] = bool(getattr(creds, "valid", False))

    expiry = getattr(creds, "expiry", None)
    if expiry is not None:
        info["expiry"] = expiry.isoformat()

    # Warning level — what the UI should show
    if info["valid"]:
        info["warning_level"] = "ok"
    elif info["has_refresh_token"]:
        # Expired but we have a refresh token → likely auto-recoverable
        info["warning_level"] = "warning"
    else:
        # Expired with no refresh token → must re-upload
        info["warning_level"] = "critical"

    return info


def save_uploaded_token(pickle_bytes: bytes) -> dict:
    """Validate and persist a pickle file uploaded by an admin.

    Returns the new status dict on success. Raises ValueError if the
    bytes don't deserialize into a Credentials-like object.
    """
    from google.oauth2.credentials import Credentials

    try:
        creds = pickle.loads(pickle_bytes)
    except Exception as e:
        raise ValueError(f"Uploaded file is not a valid pickle: {e}") from e

    if not isinstance(creds, Credentials):
        raise ValueError(
            f"Uploaded pickle is not a google.oauth2.credentials.Credentials "
            f"(got {type(creds).__name__})"
        )

    _save_token(creds)
    return get_token_status()


def build_authorize_url(redirect_uri: str) -> tuple[str, str]:
    """Build the Google OAuth consent-screen URL for the web flow.

    Returns (auth_url, state). The caller must remember `state` and pass
    it to `exchange_code_for_token` to defend against CSRF.

    Why InstalledAppFlow + a custom redirect_uri instead of Flow.from_client_secrets_file
    (web type)? Our client_secret.json is a Desktop ("installed") credential, which
    permits `http://localhost` + any path; Google additionally accepts any redirect_uri
    you pass at runtime for installed type. We use that to route the consent callback
    through our backend instead of a local browser server, so admins can authenticate
    from the deployed admin UI without SSH'ing into the VPS.
    """
    from google_auth_oauthlib.flow import Flow
    import secrets

    if not CREDENTIALS_FILE.exists():
        raise GoogleOAuthNotConfigured(
            f"OAuth credentials file not found at {CREDENTIALS_FILE}"
        )

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        # `prompt=consent` forces Google to return a refresh_token even if
        # the user has approved this app before — without it, only the very
        # first grant per user gets a refresh_token, and re-auths return
        # access_token only (which would defeat the whole point).
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return auth_url, state


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Exchange an OAuth authorization code for credentials and persist them.

    Called from the /callback endpoint after Google redirects back to us
    with `?code=…`. Saves the resulting pickle to the shared volume and
    returns the new status.
    """
    from google_auth_oauthlib.flow import Flow

    if not CREDENTIALS_FILE.exists():
        raise GoogleOAuthNotConfigured(
            f"OAuth credentials file not found at {CREDENTIALS_FILE}"
        )

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not getattr(creds, "refresh_token", None):
        # No refresh token means we'd hit the same expiry wall again in 1h.
        # This usually means the user already granted consent before and
        # Google withheld the refresh_token — `prompt=consent` should
        # prevent this but we double-check.
        raise GoogleOAuthNotConfigured(
            "OAuth completed but Google did not return a refresh_token. "
            "Revoke this app's access at https://myaccount.google.com/permissions "
            "and try again."
        )

    _save_token(creds)
    return get_token_status()


def get_drive_service_oauth():
    """Return a Drive service backed by the on-disk OAuth token.

    Tries to refresh if expired. NEVER tries to open a browser — if the
    token is missing or unrecoverable we raise GoogleOAuthNotConfigured
    with a clear instruction for the operator.
    """
    from googleapiclient.discovery import build  # lazy: worker-only dep

    creds = _load_token()

    if creds is None:
        raise GoogleOAuthNotConfigured(
            f"Google Drive OAuth token not found at {TOKEN_FILE}. "
            f"An admin must upload a token via the admin UI "
            f"(/admin/agent-config → Google OAuth section) before jobs that "
            f"use Google Drive can run."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("Refreshing expired OAuth token...")
            try:
                creds.refresh(Request())
                _save_token(creds)
            except RefreshError as e:
                logger.error(
                    f"Token refresh failed (invalid_grant): {e}. "
                    f"Admin must re-upload a token."
                )
                raise GoogleOAuthNotConfigured(
                    f"Google Drive OAuth token expired and refresh failed: {e}. "
                    f"An admin must upload a fresh token via the admin UI."
                ) from e
        else:
            raise GoogleOAuthNotConfigured(
                "Google Drive OAuth token is invalid and has no refresh "
                "token. An admin must upload a fresh token via the admin UI."
            )

    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    return service

def get_or_create_folder_oauth(service, folder_name: str = "WebReel_Presentations") -> str:
    """Get or create a folder in user's Google Drive."""
    
    # Search for existing folder
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)'
    ).execute()
    
    items = results.get('files', [])
    
    if items:
        folder_id = items[0]['id']
        logger.info(f"Found existing folder '{folder_name}' with ID: {folder_id}")
        return folder_id
    
    # Create new folder
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    
    folder = service.files().create(
        body=file_metadata,
        fields='id'
    ).execute()
    
    folder_id = folder.get('id')
    logger.info(f"Created new folder '{folder_name}' with ID: {folder_id}")
    
    return folder_id

def upload_to_gdrive_oauth(file_path: str, folder_id: str = None) -> dict:
    """
    Upload file to Google Drive using OAuth (user's Drive).
    
    Args:
        file_path: Path to the PPTX file
        folder_id: Optional folder ID to upload to
        
    Returns:
        dict: Contains 'file_id' and 'presentation_url'
    """
    from googleapiclient.http import MediaFileUpload  # lazy: worker-only dep

    service = get_drive_service_oauth()
    file_name = os.path.basename(file_path)
    
    # Get or create folder
    if not folder_id:
        folder_id = get_or_create_folder_oauth(service)
    else:
        logger.info(f"Using provided folder ID: {folder_id}")
    
    # Upload and convert to Google Slides
    file_metadata = {
        'name': file_name,
        'mimeType': 'application/vnd.google-apps.presentation',
        'parents': [folder_id]
    }
    media = MediaFileUpload(
        file_path,
        mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        resumable=True
    )
    
    logger.info(f"Uploading and converting {file_name} to Google Slides...")
    
    # Retry logic
    file = None
    for attempt in range(3):
        try:
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            break
        except Exception as e:
            logger.warning(f"Upload attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                raise e
    
    file_id = file.get('id')
    logger.info(f"Upload successful. File ID: {file_id}")
    
    # Set permissions to "anyone with link can view"
    logger.info("Setting file permissions to public (view only)...")
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    service.permissions().create(
        fileId=file_id,
        body=permission,
        fields='id'
    ).execute()
    
    # Generate presentation URL
    present_url = f"https://docs.google.com/presentation/d/{file_id}/present"
    logger.info(f"Generated Presentation URL: {present_url}")
    
    return {
        "file_id": file_id,
        "presentation_url": present_url
    }

def delete_from_gdrive_oauth(file_id: str):
    """Delete file from Google Drive using OAuth."""
    if not file_id:
        return
    try:
        service = get_drive_service_oauth()
        service.files().delete(fileId=file_id).execute()
        logger.info(f"Successfully deleted file ID {file_id} from Google Drive.")
    except Exception as e:
        logger.error(f"Failed to delete file ID {file_id}: {e}")
