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
    # 1000ms (default) cho moi truong Docker: bu jitter capture loop + cushion
    # giua narration ket thuc va ArrowRight ke tiep. Co the override per-job.
    padding_ms: int = 1000
    enable_review: bool = False
    
    # OS Worker specific config (V3 - backward compatible)
    target_pid: Optional[int] = None
    app_executable: Optional[str] = None
    
    # OS Worker V4 - Auto-launch config
    app_type: Optional[str] = None  # "excel", "word", "powerpoint", "chrome", "edge", "firefox", "notepad", "calculator", "paint"
    uploaded_file_url: Optional[str] = None  # URL to uploaded file (for Office apps)
    browser_url: Optional[str] = None  # URL to open (for browser apps)
    
    # Common config
    max_steps: int = 15
    enable_dual_output: bool = True


class JobProgress(BaseModel):
    """Progress information for running job."""
    current_phase: int
    phase_name: str
    message: str
    logs: list[str] = []


class JobResult(BaseModel):
    """Result information for completed job."""
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    document_path: Optional[str] = None
    document_url: Optional[str] = None
    pdf_path: Optional[str] = None
    pdf_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    file_sizes: Optional[dict] = None
    metadata: Optional[dict] = None


class Job(BaseModel):
    """Complete job data structure."""
    job_id: UUID = Field(default_factory=uuid4)
    status: Literal["pending", "running", "processing", "queued", "pending_review", "completed", "failed", "interrupted"]
    task: str
    video_name: str
    environment: Literal["web", "os", "presentation"] = "web"
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
    environment: Literal["web", "os", "presentation"] = Field(default="web", description="Execution environment: web (browser), os (Windows desktop), or presentation (PowerPoint/Google Slides)")
    config: JobConfig = Field(default_factory=JobConfig)
    user_id: Optional[str] = Field(None, description="User ID (optional, for tracking)")
    user_email: Optional[str] = Field(None, description="User email (optional, for notifications)")
    
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
    
    @field_validator("config")
    @classmethod
    def validate_config(cls, v: JobConfig, info) -> JobConfig:
        """Validate config based on environment."""
        # Get environment from values (already validated)
        environment = info.data.get("environment", "web")
        
        # OS environment validation
        if environment == "os":
            # V4: app_type is preferred
            # V3: target_pid or app_executable (backward compatible)
            has_v4_config = bool(v.app_type)
            has_v3_config = bool(v.target_pid or v.app_executable)
            
            if not has_v4_config and not has_v3_config:
                raise ValueError("OS environment requires either app_type (V4) or target_pid/app_executable (V3) in config")
            
            # Validate app_type if provided
            if v.app_type:
                valid_apps = ["excel", "word", "powerpoint", "chrome", "edge", "firefox", "notepad", "calculator", "paint"]
                if v.app_type not in valid_apps:
                    raise ValueError(f"Invalid app_type. Must be one of: {', '.join(valid_apps)}")
        
        return v


class JobSubmitResponse(BaseModel):
    """Response model for job submission."""
    job_id: UUID
    status: str
    created_at: datetime
    websocket_url: str
