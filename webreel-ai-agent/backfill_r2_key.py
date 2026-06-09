#!/usr/bin/env python3
"""
Backfill `result.r2_key` for jobs whose video was uploaded to R2 before
the field existed. Reads the (still public) `result.video_url`, strips
the configured R2 prefix to recover the object key, and writes it back.

Idempotent — jobs that already have r2_key are skipped. Jobs whose URL
doesn't match any R2 prefix (e.g. local-only) are skipped with a note.

Run inside the API container so MongoDB credentials are inherited:
    docker exec webreel-api python backfill_r2_key.py
"""

import asyncio
import logging
import sys
from pathlib import Path

WORKER_DIR = Path(__file__).parent
sys.path.insert(0, str(WORKER_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")


async def main() -> int:
    from backend.database import Database
    from backend.storage import R2Storage

    await Database.connect()
    db = Database.get_db()
    if db is None:
        logger.error("MongoDB not connected — aborting")
        return 1

    # Anything with a CDN-looking video_url but missing r2_key.
    query = {
        "result.video_url": {"$regex": "^https?://"},
        "$or": [
            {"result.r2_key": {"$exists": False}},
            {"result.r2_key": None},
        ],
    }

    total = 0
    backfilled = 0
    skipped = 0
    async for job in db.jobs.find(query, {"job_id": 1, "user_id": 1, "result.video_url": 1}):
        total += 1
        url = (job.get("result") or {}).get("video_url")
        key = R2Storage.derive_r2_key_from_url(url)
        if not key:
            logger.info(f"SKIP {job['job_id']}: url doesn't match R2 prefix -> {url!r}")
            skipped += 1
            continue

        await db.jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"result.r2_key": key}},
        )
        logger.info(f"OK   {job['job_id']}: r2_key={key}")
        backfilled += 1

    logger.info(
        f"Done. scanned={total} backfilled={backfilled} skipped={skipped} "
        f"(remaining without r2_key = {skipped})"
    )
    await Database.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
