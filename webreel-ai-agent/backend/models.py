"""
Pydantic data models for FastAPI backend.
Defines request/response schemas and job data structures.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime, timezone
from uuid import UUID, uuid4
import re


class JobConfig(BaseModel):
    """Configuration for video generation job."""
    enable_tts: bool = True
    tts_voice: str = "banmai"
    tts_engine: Literal["fpt", "edge"] = "fpt"
    cdp_url: str = "http://localhost:9222"
    padding_ms: int = 300


class JobProgress(BaseModel):
    """Progress information for running job."""
    current_phase: int
    phase_name: str
    message: str
    logs: list[str] = []


class JobResult(BaseModel):
    """Result information for completed job."""
    video_path: str
    video_url: str
    duration_seconds: Optional[float] = None


class Job(BaseModel):
    """Complete job data structure."""
    job_id: UUID = Field(default_factory=uuid4)
    status: Literal["pending", "running", "completed", "failed", "interrupted"]
    task: str
    video_name: str
    config: JobConfig
    progress: Optional[JobProgress] = None
    result: Optional[JobResult] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobSubmitRequest(BaseModel):
    """Request model for job submission."""
    task: str = Field(..., min_length=1, max_length=1000, description="Task description for video generation")
    video_name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$", description="Output video name (alphanumeric, underscore, hyphen only)")
    config: JobConfig = Field(default_factory=JobConfig)
    
    @field_validator("task")
    @classmethod
    def validate_task(cls, v: str) -> str:
        """Validate task description is not empty after stripping."""
        if not v.strip():
            raise ValueError("Task description cannot be empty")
        return v.strip()
    
    @field_validator("video_name")
    @classmethod
    def validate_video_name(cls, v: str) -> str:
        """Validate video name format."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Video name must contain only alphanumeric characters, underscores, and hyphens")
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Video name must be between 1 and 100 characters")
        return v


class JobSubmitResponse(BaseModel):
    """Response model for job submission."""
    job_id: UUID
    status: str
    created_at: datetime
    websocket_url: str
