"""
Redis-based job queue for WebReel production.

Supports 3 queue types:
  - web-queue: Web tutorial recording (Linux Docker)
  - office-queue: Office Viewer PPTX recording (Linux Docker)
  - os-queue: OS native automation (Windows worker)

Reliability:
  - Uses BRPOPLPUSH for safe dequeue (job moves to processing queue)
  - If worker crashes, job remains in processing queue for recovery
  - Supports Redis AUTH password
  - In-memory fallback for development (no Redis needed)
"""

import json
import os
import time
import logging
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis package not installed. Queue will use in-memory fallback.")


class JobQueue:
    """Redis-backed job queue with reliable dequeue and result storage."""

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = None
        self._fallback_queues = {}  # In-memory fallback for development

    @property
    def redis(self):
        """Lazy Redis connection with password support."""
        if self._redis is None and REDIS_AVAILABLE:
            try:
                self._redis = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                )
                self._redis.ping()
                logger.info(f"Redis connected: {self._sanitize_url(self.redis_url)}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
                self._redis = None
        return self._redis

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Hide password in Redis URL for logging."""
        if "@" in url:
            parts = url.split("@")
            return f"redis://***@{parts[-1]}"
        return url

    def push(self, queue_name: str, job_data: dict) -> str:
        """Push a job to the specified queue. Returns job_id."""
        job_id = job_data.get("job_id", str(uuid4()))
        job_data["job_id"] = job_id
        job_data["queued_at"] = time.time()
        job_data["status"] = "queued"

        payload = json.dumps(job_data, ensure_ascii=False, default=str)

        if self.redis:
            self.redis.rpush(queue_name, payload)
            self.redis.set(f"job:{job_id}:status", "queued", ex=86400)
            # Notify autoscaler instantly via Pub/Sub
            self.redis.publish(
                "new-job",
                json.dumps({"job_id": job_id, "queue": queue_name}),
            )
            logger.info(f"RPUSH {queue_name}: Job {job_id}")
        else:
            if queue_name not in self._fallback_queues:
                self._fallback_queues[queue_name] = []
            self._fallback_queues[queue_name].append(payload)
            logger.info(f"[Memory] Push {queue_name}: Job {job_id}")

        return job_id

    def poll(self, queue_name: str, timeout: int = 5) -> Optional[dict]:
        """Safely dequeue a job using BRPOPLPUSH pattern.
        
        The job is atomically moved from queue_name to queue_name:processing.
        If the worker crashes, the job stays in the processing queue and can
        be recovered by calling recover_stale_jobs().
        
        After successful processing, call ack(queue_name, job) to remove
        the job from the processing queue.
        """
        processing_queue = f"{queue_name}:processing"

        if self.redis:
            # BRPOPLPUSH: atomically pop from queue and push to processing
            # This ensures the job is never lost even if worker crashes
            payload = self.redis.brpoplpush(
                queue_name, processing_queue, timeout=timeout
            )
            if payload:
                job = json.loads(payload)
                self.redis.set(
                    f"job:{job['job_id']}:status", "processing", ex=86400
                )
                self.redis.set(
                    f"job:{job['job_id']}:started_at", time.time(), ex=86400
                )
                logger.info(f"BRPOPLPUSH {queue_name}: Job {job['job_id']}")
                return job
        else:
            # In-memory fallback
            q = self._fallback_queues.get(queue_name, [])
            if q:
                payload = q.pop(0)
                return json.loads(payload)
            time.sleep(min(timeout, 1))

        return None

    def ack(self, queue_name: str, job: dict):
        """Acknowledge successful processing - remove job from processing queue.
        
        Call this AFTER set_result() to confirm the job was fully processed.
        """
        processing_queue = f"{queue_name}:processing"
        if self.redis:
            payload = json.dumps(job, ensure_ascii=False, default=str)
            removed = self.redis.lrem(processing_queue, 1, payload)
            if removed:
                logger.debug(f"ACK {queue_name}: Job {job.get('job_id')}")

    def recover_stale_jobs(self, queue_name: str, max_age_seconds: int = 600):
        """Recover jobs stuck in processing queue (worker crashed).
        
        Re-queues jobs that have been in processing for longer than max_age_seconds.
        Call this periodically from the API or a cron job.
        """
        processing_queue = f"{queue_name}:processing"
        if not self.redis:
            return 0

        recovered = 0
        stale_jobs = self.redis.lrange(processing_queue, 0, -1)

        for payload in stale_jobs:
            try:
                job = json.loads(payload)
                started_at = self.redis.get(f"job:{job['job_id']}:started_at")
                if started_at and (time.time() - float(started_at)) > max_age_seconds:
                    # Re-queue the stale job
                    self.redis.lrem(processing_queue, 1, payload)
                    job["retry_count"] = job.get("retry_count", 0) + 1
                    job["recovered_at"] = time.time()
                    self.push(queue_name, job)
                    logger.warning(
                        f"Recovered stale job {job['job_id']} from {processing_queue} "
                        f"(was processing for {time.time() - float(started_at):.0f}s)"
                    )
                    recovered += 1
            except Exception as e:
                logger.error(f"Error recovering job: {e}")

        return recovered

    def set_result(self, job_id: str, result: dict, ttl: int = 86400):
        """Store job result in Redis. TTL defaults to 24 hours."""
        payload = json.dumps(result, ensure_ascii=False, default=str)

        if self.redis:
            self.redis.set(f"job:{job_id}:result", payload, ex=ttl)
            self.redis.set(
                f"job:{job_id}:status",
                result.get("status", "completed"),
                ex=ttl,
            )
            logger.info(
                f"Result stored: Job {job_id} -> {result.get('status', 'completed')}"
            )
        else:
            logger.info(
                f"[Memory] Result: Job {job_id} -> {result.get('status', 'completed')}"
            )

    def get_result(self, job_id: str) -> Optional[dict]:
        """Get job result from Redis."""
        if self.redis:
            payload = self.redis.get(f"job:{job_id}:result")
            if payload:
                return json.loads(payload)
        return None

    def get_status(self, job_id: str) -> Optional[str]:
        """Get job status from Redis."""
        if self.redis:
            return self.redis.get(f"job:{job_id}:status")
        return None

    def get_queue_length(self, queue_name: str) -> int:
        """Get number of jobs waiting in queue."""
        if self.redis:
            return self.redis.llen(queue_name)
        return len(self._fallback_queues.get(queue_name, []))

    def get_processing_length(self, queue_name: str) -> int:
        """Get number of jobs currently being processed."""
        if self.redis:
            return self.redis.llen(f"{queue_name}:processing")
        return 0

    def get_all_queue_stats(self) -> dict:
        """Get stats for all queues (waiting + processing)."""
        queues = [
            "web-queue", "office-queue", "os-queue",
            "presentation-queue", "presentation-gg-queue",
        ]
        stats = {}
        for q in queues:
            stats[q] = {
                "waiting": self.get_queue_length(q),
                "processing": self.get_processing_length(q),
            }
        return stats

    def register_worker(self, job_id: str, container_name: str, ttl: int = 7200):
        """Register which container is running a job.

        Stores mapping job_id -> container_name in Redis so the autoscaler
        can stop the correct container when a job needs to be killed.
        TTL defaults to 2 hours (safety net for orphaned entries).
        """
        if self.redis:
            self.redis.set(f"job:{job_id}:worker", container_name, ex=ttl)
            logger.info(f"Registered worker: job {job_id} -> {container_name}")

    def get_worker_for_job(self, job_id: str) -> Optional[str]:
        """Look up which container is running a given job."""
        if self.redis:
            return self.redis.get(f"job:{job_id}:worker")
        return None

    def unregister_worker(self, job_id: str):
        """Remove job-to-container mapping after job completes."""
        if self.redis:
            self.redis.delete(f"job:{job_id}:worker")
            logger.debug(f"Unregistered worker for job {job_id}")

    def notify_api(self, job_id: str, channel: str = "job-updates"):
        """Publish job completion to Redis Pub/Sub for API WebSocket broadcast."""
        if self.redis:
            self.redis.publish(
                channel,
                json.dumps(
                    {
                        "job_id": job_id,
                        "event": "completed",
                        "timestamp": time.time(),
                    }
                ),
            )

    def notify_api_progress(self, job_id: str, phase: float, message: str, data: dict = None, channel: str = "job-updates"):
        """Publish job progress to Redis Pub/Sub for API WebSocket broadcast."""
        if self.redis:
            self.redis.publish(
                channel,
                json.dumps(
                    {
                        "job_id": job_id,
                        "event": "progress",
                        "progress": {
                            "current_phase": phase,
                            "phase_name": message,
                            "message": message,
                            "data": data,
                        },
                        "timestamp": time.time(),
                    }
                ),
            )
            
    async def wait_for_review(self, job_id: str, timeout_seconds: int = 1800) -> Optional[list]:
        """Wait for an approved TTS script to be published via Redis Pub/Sub.
        
        Args:
            job_id: The job ID to wait for.
            timeout_seconds: Maximum time to wait in seconds (default 30 mins).
            
        Returns:
            list: The approved TTS script, or None if timed out.
        """
        import asyncio
        if not self.redis:
            logger.warning("Redis not available, wait_for_review will timeout immediately.")
            return None
            
        # We need an async redis connection to use pubsub in asyncio
        import redis.asyncio as aioredis
        
        # Determine the channel name
        review_channel = f"job:{job_id}:review_approved"
        
        logger.info(f"Worker waiting for review on {review_channel} (timeout: {timeout_seconds}s)")
        
        try:
            # Create a dedicated async connection for PubSub.
            #
            # redis-py 8.0 broke pubsub.listen(): it now defaults to a 5-second
            # socket read timeout even on a long-blocking subscribe, so
            # `async for msg in pubsub.listen()` raises TimeoutError after 5s
            # instead of blocking until a message arrives. We explicitly set
            # socket_timeout=None (no read timeout — block forever) and add
            # health_check_interval so the connection still gets keep-alive
            # PINGs every 30s for liveness.
            async_redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=None,
                socket_keepalive=True,
                health_check_interval=30,
            )
            pubsub = async_redis.pubsub()
            await pubsub.subscribe(review_channel)
            
            async def _wait():
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        return data.get("tts_script")
            
            # Wait with timeout (to prevent Zombie Worker)
            try:
                result = await asyncio.wait_for(_wait(), timeout=timeout_seconds)
                logger.info(f"Received approved script for job {job_id}")
                return result
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for review for job {job_id}. Proceeding with default script.")
                return None
            finally:
                await pubsub.unsubscribe(review_channel)
                await async_redis.aclose()
                
        except Exception as e:
            logger.error(f"Error waiting for review: {e}")
            return None
            
    def submit_review(self, job_id: str, tts_script: list):
        """Publish the approved TTS script to unblock the waiting worker."""
        if self.redis:
            review_channel = f"job:{job_id}:review_approved"
            self.redis.publish(
                review_channel,
                json.dumps({"job_id": job_id, "tts_script": tts_script})
            )
            logger.info(f"Published approved review for job {job_id} to {review_channel}")

    # ---------------------------------------------------------------------------
    # Queue pause/resume for Circuit Breaker
    # ---------------------------------------------------------------------------
    def pause_queue(self, queue_name: str, reason: str = "session_expired", ttl: int = 86400):
        """Pause a queue due to session expiry (Circuit Breaker).

        When a queue is paused, no new workers will be spawned for it.
        The pause status is stored in Redis with TTL.
        """
        if self.redis:
            key = f"queue:{queue_name}:paused"
            self.redis.set(key, json.dumps({
                "reason": reason,
                "paused_at": time.time(),
            }), ex=ttl)
            logger.warning(f"Queue {queue_name} PAUSED: {reason}")

    def resume_queue(self, queue_name: str):
        """Resume a previously paused queue."""
        if self.redis:
            key = f"queue:{queue_name}:paused"
            self.redis.delete(key)
            logger.info(f"Queue {queue_name} RESUMED")

    def is_queue_paused(self, queue_name: str) -> bool:
        """Check if a queue is currently paused."""
        if self.redis:
            key = f"queue:{queue_name}:paused"
            return self.redis.exists(key) > 0
        return False

    def get_queue_pause_info(self, queue_name: str) -> Optional[dict]:
        """Get pause information for a queue."""
        if self.redis:
            key = f"queue:{queue_name}:paused"
            data = self.redis.get(key)
            if data:
                return json.loads(data)
        return None
