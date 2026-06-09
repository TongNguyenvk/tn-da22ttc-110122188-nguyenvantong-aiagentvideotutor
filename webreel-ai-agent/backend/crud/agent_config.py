"""
CRUD for agent runtime config (API keys + model name).

Singleton document in `agent_configs` collection — there is exactly one
config row keyed by `_id="default"`. Workers don't read from MongoDB
directly; the autoscaler reads this doc and injects the values as `-e`
env overrides on `docker compose run`, so each job picks up the latest
key/model without rebuilding worker images.
"""

from datetime import datetime, timezone
from typing import Optional

# Note: `from backend.database import Database` is imported lazily inside the
# async fns below. The autoscaler image only installs `redis` + `pymongo` and
# does not have motor available, so a top-level Database import would crash
# the autoscaler at startup just by virtue of loading this module.


CONFIG_ID = "default"
COLLECTION = "agent_configs"

# Fallbacks when MongoDB has no row yet — match docker-compose.prod.yml defaults
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_TTS_PROVIDER = "edge"  # edge | fpt — Edge is free + no key required


def _empty_config() -> dict:
    return {
        "_id": CONFIG_ID,
        "gemini_api_key": "",
        "gemini_model": DEFAULT_GEMINI_MODEL,
        "fpt_api_key": "",
        "tts_default_provider": DEFAULT_TTS_PROVIDER,
        "tts_default_voice": "",
        # Subset of SUPPORTED_TTS_PROVIDERS that admin has enabled.
        # Edge requires no key so it's enabled by default; FPT only if
        # admin saved a key.
        "tts_enabled_providers": ["edge"],
        "updated_at": None,
        "updated_by": None,
    }


async def get_agent_config() -> dict:
    """Return the current agent config, or defaults if not set."""
    from backend.database import Database

    db = Database.get_db()
    if db is None:
        return _empty_config()

    doc = await db[COLLECTION].find_one({"_id": CONFIG_ID})
    if not doc:
        return _empty_config()

    # Backfill missing keys for forward-compat
    base = _empty_config()
    base.update(doc)
    return base


async def update_agent_config(
    updates: dict,
    updated_by: Optional[str] = None,
) -> dict:
    """Upsert allowed fields and return the new config.

    Only whitelisted keys are written; everything else is ignored so a
    malformed admin payload can't pollute the document.
    """
    from backend.database import Database

    db = Database.get_db()
    if db is None:
        raise RuntimeError("MongoDB not connected — cannot persist agent config")

    allowed = {
        "gemini_api_key",
        "gemini_model",
        "fpt_api_key",
        "tts_default_provider",
        "tts_default_voice",
        "tts_enabled_providers",
    }
    payload = {k: v for k, v in updates.items() if k in allowed and v is not None}

    if not payload:
        return await get_agent_config()

    payload["updated_at"] = datetime.now(timezone.utc)
    if updated_by:
        payload["updated_by"] = updated_by

    await db[COLLECTION].update_one(
        {"_id": CONFIG_ID},
        {"$set": payload},
        upsert=True,
    )

    return await get_agent_config()


def get_agent_config_sync() -> dict:
    """Sync variant for the autoscaler (which is a plain Python loop, no asyncio).

    Uses pymongo directly because Motor only exposes async APIs.
    """
    import os
    from pymongo import MongoClient

    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "webreel")

    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
        doc = client[db_name][COLLECTION].find_one({"_id": CONFIG_ID})
        client.close()
    except Exception:
        return _empty_config()

    if not doc:
        return _empty_config()

    base = _empty_config()
    base.update(doc)
    return base
