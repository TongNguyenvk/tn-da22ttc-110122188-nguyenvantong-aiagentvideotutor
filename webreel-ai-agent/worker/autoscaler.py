"""
Auto-scaler for WebReel workers (1 Worker = 1 Job).

Event-driven scaling using Redis Pub/Sub:
  - Listens for new-job events and launches a dedicated container per job.
  - Listens for job-kill events and stops the target container.
  - Each worker container processes exactly ONE job then exits.
  - Containers are launched via `docker compose run --rm` so they auto-remove.

Usage (inside Docker with access to /var/run/docker.sock):
    python -m worker.autoscaler

Environment:
    REDIS_URL          - Redis connection string
    MAX_WEB_WORKERS    - Max concurrent web workers (default: 2)
    MAX_PRES_WORKERS   - Max concurrent presentation workers (default: 2)
    MAX_PRES_GG_WORKERS - Max concurrent presentation-gg workers (default: 2)
    MAX_OFFICE_WORKERS - Max concurrent office workers (default: 2)
    COMPOSE_FILE       - Path to docker-compose.prod.yml
    COMPOSE_PROJECT    - Docker compose project name
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKER_DIR = Path(__file__).parent
AGENT_DIR = WORKER_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from backend.queue import JobQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [autoscaler] %(levelname)s - %(message)s",
)
logger = logging.getLogger("autoscaler")

# Compose configuration
COMPOSE_FILE = os.getenv("COMPOSE_FILE", "docker-compose.prod.yml")
COMPOSE_PROJECT = os.getenv("COMPOSE_PROJECT", "webreel-ai-agent")


def _compose_base_cmd() -> list[str]:
    """Build the base docker compose command."""
    return ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT]


def _detect_host_project_dir() -> str:
    """Auto-detect the HOST project directory from existing container labels.

    Reads com.docker.compose.project.working_dir from a running container
    in the same compose project. This is the absolute path on the HOST where
    docker-compose.prod.yml lives, needed so worker volume mounts (e.g.
    ${HOST_PROJECT_DIR:-.}/output) resolve correctly.
    """
    try:
        result = subprocess.run(
            [
                "docker", "ps",
                "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}",
                "--format", "{{.ID}}",
                "-n", "1",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            cid = result.stdout.strip().split("\n")[0]
            inspect = subprocess.run(
                ["docker", "inspect", cid, "--format",
                 "{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}"],
                capture_output=True, text=True, timeout=10,
            )
            if inspect.returncode == 0 and inspect.stdout.strip():
                return inspect.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to detect host project dir: {e}")
    return ""

# Per-queue worker limits
QUEUE_CONFIG = {
    "web-queue": {
        "service": "web-worker",
        "max_workers": int(os.getenv("MAX_WEB_WORKERS", "2")),
    },
    "presentation-queue": {
        "service": "presentation-worker",
        "max_workers": int(os.getenv("MAX_PRES_WORKERS", "2")),
    },
    "presentation-gg-queue": {
        "service": "presentation-gg-worker",
        "max_workers": int(os.getenv("MAX_PRES_GG_WORKERS", "2")),
    },
    "office-queue": {
        "service": "office-worker",
        "max_workers": int(os.getenv("MAX_OFFICE_WORKERS", "2")),
    },
}


class AutoScaler:
    """Event-driven auto-scaler: 1 container per job."""

    def __init__(self):
        self.queue = JobQueue()
        self._lock = threading.Lock()
        # Auto-detect the HOST path where compose project lives.
        # This is injected as HOST_PROJECT_DIR into `docker compose run`
        # so volume paths like ${HOST_PROJECT_DIR:-.}/output resolve to
        # absolute host paths instead of paths inside the autoscaler container.
        self._host_project_dir = _detect_host_project_dir()
        if self._host_project_dir:
            logger.info(f"  Host project dir: {self._host_project_dir}")
        else:
            logger.warning("Could not detect host project dir. Volume mounts may fail.")

    def _get_compose_env(self) -> dict:
        """Build environment dict for subprocess calls to docker compose.

        Inherits current env and adds HOST_PROJECT_DIR so the compose file
        can resolve volume paths correctly.
        """
        env = os.environ.copy()
        if self._host_project_dir:
            env["HOST_PROJECT_DIR"] = self._host_project_dir
        return env

    # ------------------------------------------------------------------
    # Container management
    # ------------------------------------------------------------------

    def count_running_containers(self, service: str) -> int:
        """Count running containers for a given compose service."""
        try:
            result = subprocess.run(
                [
                    "docker", "ps",
                    "--filter", f"label=com.docker.compose.service={service}",
                    "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}",
                    "--filter", "status=running",
                    "--format", "{{.ID}}",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                return len(lines)
        except Exception as e:
            logger.warning(f"Failed to count containers for {service}: {e}")
        return 0

    def _build_env_overrides(self) -> list[str]:
        """Read latest agent config from Mongo and emit `-e KEY=VAL` args.

        Workers normally inherit GEMINI_API_KEY / GEMINI_MODEL / FPT_API_KEY
        from docker-compose.prod.yml (which reads the host .env). When an
        admin sets values via the UI, we override them here so the NEW
        container picks them up at boot — no image rebuild, no compose
        restart needed. Empty values are skipped so the compose default
        still applies if no admin override exists.
        """
        try:
            from backend.crud.agent_config import get_agent_config_sync
            cfg = get_agent_config_sync()
        except Exception as e:
            logger.warning(f"Could not load agent config from Mongo: {e}")
            return []

        overrides: list[str] = []

        # Gemini + FPT (uppercase env names match what workers already read)
        for env_key in ("gemini_api_key", "gemini_model", "fpt_api_key"):
            value = (cfg.get(env_key) or "").strip()
            if not value:
                continue
            overrides.extend(["-e", f"{env_key.upper()}={value}"])

        # TTS defaults — workers read these as fallbacks when the job config
        # doesn't pin a provider/voice. Workers themselves still honour
        # config.tts_engine / config.tts_voice on the job; these env vars
        # only kick in when the user accepted the default.
        for env_key, env_name in (
            ("tts_default_provider", "TTS_DEFAULT_PROVIDER"),
            ("tts_default_voice", "TTS_DEFAULT_VOICE"),
        ):
            value = (cfg.get(env_key) or "").strip()
            if value:
                overrides.extend(["-e", f"{env_name}={value}"])

        if overrides:
            # Log model + masked key so we can verify what the worker will see
            model = cfg.get("gemini_model") or "(unset)"
            has_key = "set" if cfg.get("gemini_api_key") else "unset"
            has_fpt = "set" if cfg.get("fpt_api_key") else "unset"
            tts = cfg.get("tts_default_provider") or "(unset)"
            logger.info(
                f"Injecting admin overrides: model={model}, gemini_key={has_key}, "
                f"fpt_key={has_fpt}, tts_default={tts}"
            )
        return overrides

    def launch_worker(self, service: str, job_id: str) -> bool:
        """Launch a new worker container for a specific job.

        Uses `docker compose run -d --rm` to create an ephemeral container
        that auto-removes when it exits.
        """
        container_name = f"webreel-{service}-{job_id[:8]}"

        logger.info(f"Launching {service} container: {container_name} for job {job_id}")

        try:
            env_overrides = self._build_env_overrides()

            cmd = _compose_base_cmd() + [
                "run", "-d", "--rm",
                "--name", container_name,
                *env_overrides,
                service,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30,
                env=self._get_compose_env(),
            )

            if result.returncode == 0:
                logger.info(f"Container {container_name} launched successfully")
                return True
            else:
                logger.error(
                    f"Failed to launch {container_name}: {result.stderr.strip()}"
                )
                return False

        except Exception as e:
            logger.error(f"Error launching {container_name}: {e}")
            return False

    def stop_container(self, container_name: str) -> bool:
        """Stop a running container by name or ID."""
        logger.info(f"Stopping container: {container_name}")
        try:
            result = subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                logger.info(f"Container {container_name} stopped")
                return True
            else:
                logger.warning(f"Failed to stop {container_name}: {result.stderr.strip()}")
                return False
        except Exception as e:
            logger.error(f"Error stopping {container_name}: {e}")
            return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_new_job(self, queue_name: str, job_id: str):
        """Called when a new job arrives. Launch a worker if capacity allows."""
        with self._lock:
            config = QUEUE_CONFIG.get(queue_name)
            if not config:
                logger.warning(f"Unknown queue: {queue_name}, ignoring")
                return

            # Circuit Breaker: skip if queue is paused (session expired)
            if self.queue.is_queue_paused(queue_name):
                pause_info = self.queue.get_queue_pause_info(queue_name)
                logger.warning(
                    f"Queue {queue_name} is PAUSED (session expired). "
                    f"Will not launch workers. Reason: {pause_info}"
                )
                return

            service = config["service"]
            max_workers = config["max_workers"]

            running = self.count_running_containers(service)
            logger.info(
                f"Queue {queue_name}: {running}/{max_workers} workers running"
            )

            if running >= max_workers:
                logger.info(
                    f"Max workers reached for {service} ({running}/{max_workers}). "
                    f"Job {job_id} will wait in queue."
                )
                return

            self.launch_worker(service, job_id)

    def handle_kill_job(self, job_id: str):
        """Called when a job needs to be killed. Stop the container running it."""
        with self._lock:
            # Look up which container is running this job
            container_name = self.queue.get_worker_for_job(job_id)

            if container_name:
                logger.info(f"Killing job {job_id}: stopping container {container_name}")
                self.stop_container(container_name)
                self.queue.unregister_worker(job_id)
            else:
                # Try brute-force name pattern match
                for qconfig in QUEUE_CONFIG.values():
                    guess = f"webreel-{qconfig['service']}-{job_id[:8]}"
                    logger.info(f"Trying container name guess: {guess}")
                    if self.stop_container(guess):
                        break
                else:
                    logger.warning(
                        f"No container found for job {job_id}. "
                        f"Job may have already completed or not started."
                    )

    # ------------------------------------------------------------------
    # Redis listeners
    # ------------------------------------------------------------------

    def listen_for_events(self):
        """Subscribe to Redis for job notifications (new-job + job-kill)."""
        if not self.queue.redis:
            logger.error("Redis not available. Autoscaler requires Redis.")
            return

        pubsub = self.queue.redis.pubsub()
        pubsub.subscribe("new-job", "job-kill")

        logger.info("Listening for events on channels: new-job, job-kill")

        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                channel = message["channel"]
                data = json.loads(message["data"])

                if channel == "new-job":
                    queue_name = data.get("queue", "unknown")
                    job_id = data.get("job_id", "unknown")
                    logger.info(f"Event [new-job]: {job_id} -> {queue_name}")
                    self.handle_new_job(queue_name, job_id)

                elif channel == "job-kill":
                    job_id = data.get("job_id", "unknown")
                    logger.info(f"Event [job-kill]: {job_id}")
                    self.handle_kill_job(job_id)

            except Exception as e:
                logger.warning(f"Error handling event: {e}")

    def run_cleanup(self):
        """Periodically clean up orphaned containers that are stuck."""
        while True:
            time.sleep(300)  # Every 5 minutes
            try:
                # List all exited worker containers and remove them
                for config in QUEUE_CONFIG.values():
                    service = config["service"]
                    result = subprocess.run(
                        [
                            "docker", "ps", "-a",
                            "--filter", f"label=com.docker.compose.service={service}",
                            "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}",
                            "--filter", "status=exited",
                            "--format", "{{.ID}}",
                        ],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode == 0:
                        containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
                        for cid in containers:
                            subprocess.run(
                                ["docker", "rm", cid],
                                capture_output=True, timeout=10,
                            )
                            logger.debug(f"Removed exited container: {cid}")
                        if containers:
                            logger.info(f"Cleaned up {len(containers)} exited {service} containers")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")


def run_autoscaler():
    """Main entry point."""
    scaler = AutoScaler()

    logger.info("WebReel Auto-Scaler started (1 Worker = 1 Job)")
    logger.info(f"  Compose file: {COMPOSE_FILE}")
    logger.info(f"  Compose project: {COMPOSE_PROJECT}")
    logger.info(f"  Redis: {scaler.queue._sanitize_url(scaler.queue.redis_url)}")
    logger.info(f"  Queue config:")
    for queue_name, config in QUEUE_CONFIG.items():
        logger.info(f"    {queue_name}: service={config['service']}, max={config['max_workers']}")

    # Start cleanup thread in background
    cleanup_thread = threading.Thread(target=scaler.run_cleanup, daemon=True)
    cleanup_thread.start()

    # Main thread: listen for events (blocking)
    try:
        scaler.listen_for_events()
    except KeyboardInterrupt:
        logger.info("Auto-scaler shutting down")


if __name__ == "__main__":
    run_autoscaler()
