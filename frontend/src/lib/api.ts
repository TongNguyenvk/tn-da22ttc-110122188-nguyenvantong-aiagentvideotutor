export type VideoStatus =
  | "pending"
  | "queued"
  | "running"
  | "processing"
  | "pending_review"
  | "completed"
  | "failed"
  | "cancelled";

export interface Video {
  id: string | number;
  title: string;
  status: VideoStatus;
  duration?: string;
  date: string;
  thumbnail?: string | null;
  video_url?: string;
  jobId?: string;
  user_id?: string;
  user_name?: string | null;
  user_status?: string | null;
  user_tier?: string | null;
  task?: string;
  video_name?: string;
  job_type?: string;
  config?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  progress?: JobProgress | null;
  error?: string | null;
  cancel_message?: string | null;
  cancel_reason_label?: string | null;
  cancelled_by_role?: "user" | "admin" | string | null;
  cancelled_at?: string | null;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface JobProgress {
  current_phase?: number;
  phase_name?: string;
  message?: string;
  data?: unknown;
}

export interface JobDetail {
  job_id: string;
  status: VideoStatus;
  task: string;
  video_name: string;
  config: Record<string, unknown>;
  job_type?: string;
  progress?: JobProgress | null;
  result?: {
    video_path?: string;
    video_url?: string;
    duration_seconds?: number | null;
  } | null;
  error?: string | null;
  cancel_message?: string | null;
  cancel_reason_label?: string | null;
  cancelled_by_role?: "user" | "admin" | string | null;
  cancelled_at?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

// Dung bien moi truong Vite, fallback ve localhost khi dev
const API_BASE = import.meta.env.VITE_API_URL || "/api";

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("token");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function fetchVideos(): Promise<Video[]> {
  try {
    const res = await fetch(`${API_BASE}/jobs/`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch videos");
    const data = await res.json();

    // Map response cua FastAPI thanh chuan UI (data.jobs)
    return data.jobs.map((job: any) => ({
      id: job.job_id,
      title: job.video_name || job.task?.slice(0, 35) + "...",
      status: job.status,
      date: new Date(job.created_at).toLocaleString(),
      video_url: job.result?.video_url,
      duration: job.result?.duration_seconds ? `${job.result.duration_seconds}s` : "--",
      progress: job.progress || null,
      error: job.error || null,
      cancel_message: job.cancel_message || null,
      cancel_reason_label: job.cancel_reason_label || null,
      cancelled_by_role: job.cancelled_by_role || null,
      cancelled_at: job.cancelled_at || null,
    }));
  } catch (error) {
    console.error("API Error: Backend offline or CORS issue.", error);
    return [];
  }
}

export async function createVideo(data: {
  prompt: string;
  job_type: string;
  tts_engine: string;
  tts_voice: string;
  padding_ms: number;
  enable_tts: boolean;
  enable_review: boolean;
  file?: File;
  // V4 OS Worker fields
  app_type?: string;
  browser_url?: string;
}): Promise<Video> {
  let res;

  if (data.file && data.job_type === "presentation") {
    const formData = new FormData();
    formData.append("file", data.file);
    formData.append("task", data.prompt);
    formData.append("tts_engine", data.tts_engine);
    formData.append("tts_voice", data.tts_voice);
    formData.append("padding_ms", String(data.padding_ms));
    formData.append("enable_review", String(data.enable_review));

    // V4: Add app_type and browser_url if present
    if (data.app_type) {
      formData.append("app_type", data.app_type);
    }
    if (data.browser_url) {
      formData.append("browser_url", data.browser_url);
    }

    const token = localStorage.getItem("token");

    // Route to correct endpoint based on job type
    const endpoint =
      data.job_type === "presentation"
        ? `${API_BASE}/upload-pptx-gg`
        : `${API_BASE}/jobs/upload-file`; // V4 OS Worker endpoint

    res = await fetch(endpoint, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
  } else {
    let uploadedFileUrl: string | undefined;

    if (data.file) {
      const formData = new FormData();
      formData.append("file", data.file);

      const token = localStorage.getItem("token");
      const uploadRes = await fetch(`${API_BASE}/jobs/upload-file`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });

      if (!uploadRes.ok) {
        const errorData = await uploadRes.json().catch(() => ({}));
        throw new Error(errorData.detail || "Upload file failed");
      }

      const uploadResult = await uploadRes.json();
      uploadedFileUrl = uploadResult.file_url;
    }

    const payload = {
      task: data.prompt,
      job_type: data.job_type,
      config: {
        tts_engine: data.tts_engine,
        tts_voice: data.tts_voice,
        padding_ms: data.padding_ms,
        enable_tts: data.enable_tts,
        enable_review: data.enable_review,
        // V4 OS Worker config
        ...(data.app_type && { app_type: data.app_type }),
        ...(uploadedFileUrl && { uploaded_file_url: uploadedFileUrl }),
        ...(data.browser_url && { browser_url: data.browser_url }),
      },
    };

    res = await fetch(`${API_BASE}/queue/submit`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
  }

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Create job failed");
  }

  const result = await res.json();
  return {
    id: result.job_id,
    title: data.prompt.slice(0, 35) + "...",
    status: result.status || "pending",
    date: new Date().toISOString(),
  };
}

// Lay chi tiet 1 job (dung cho dialog xem chi tiet)
export async function getJobDetail(jobId: string): Promise<JobDetail> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to get job detail");
  return res.json();
}

export async function cancelMyJob(jobId: string): Promise<{
  message: string;
  job_id: string;
  status: VideoStatus;
}> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Không thể dừng job");
  }
  return res.json();
}

// Lay TTS script de review (Phase 2.5)
export async function getJobScript(jobId: string) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/script`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to get job script");
  const data = await res.json();
  // Backend tra { script: { segments: [...], ... } }
  return data.script;
}

// Gui script da duyet de tiep tuc pipeline
export async function approveScript(jobId: string, ttsScript: any[]) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/review`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ tts_script: ttsScript }),
  });
  if (!res.ok) throw new Error("Failed to approve script");
  return res.json();
}

// Tao URL download video (dung endpoint /api/jobs/{id}/video)
export function getVideoDownloadUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/video`;
}

// Lấy URL xem video. Backend kiểm owner + cấp signed URL ngắn hạn (10 phút).
// Không expose R2 CDN URL trực tiếp ra client nữa — link cũ leak ai cũng xem được.
export async function getVideoViewUrl(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/view?json=true`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Không lấy được URL xem video");
  }
  const data = await res.json();
  return data.url;
}

// URL xem truoc video (stream qua static files)
// Nginx proxy /videos/ toi backend, chi can dung relative path
// DEPRECATED: dùng getVideoViewUrl() — nó kiểm owner và cấp signed URL.
export function getVideoPreviewUrl(videoUrl: string | undefined): string | null {
  if (!videoUrl) return null;
  if (videoUrl.startsWith("http")) return videoUrl;
  return videoUrl;
}

// Admin API functions
export interface AdminUser {
  user_id: string;
  email: string;
  name: string;
  role: "user" | "admin";
  tier: string;
  status: string;
  email_verified: boolean;
  quota: {
    videos_per_month: number;
    videos_used_this_month: number;
  };
  created_at: string;
  last_login?: string;
}

export interface AdminCreateUserPayload {
  email: string;
  name: string;
  password: string;
  role: "user" | "admin";
  tier: string;
  videos_per_month: number;
}

export interface CurrentUserProfile {
  user_id: string;
  email: string;
  name: string;
  auth_provider: "local" | "google" | "both";
  avatar_url?: string | null;
  role: "user" | "admin";
  tier: string;
  status: string;
  email_verified: boolean;
  quota: {
    videos_per_month: number;
    videos_used_this_month: number;
  };
  created_at: string;
  last_login?: string;
}

export async function fetchCurrentUserProfile(): Promise<CurrentUserProfile> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Không thể tải thông tin tài khoản");
  return res.json();
}

export interface AdminStats {
  jobs: {
    total: number;
    by_status: Record<string, number>;
  };
  users: {
    total: number;
    active: number;
    suspended: number;
    by_tier: {
      free: number;
      pro: number;
      enterprise: number;
    };
    by_role: {
      admin: number;
      user: number;
    };
  };
}

export async function fetchAllUsers(): Promise<AdminUser[]> {
  const res = await fetch(`${API_BASE}/admin/users`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch users");
  const data = await res.json();
  return data.users;
}

export async function fetchAllJobs(): Promise<Video[]> {
  const res = await fetch(`${API_BASE}/admin/jobs`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch all jobs");
  const data = await res.json();

  return data.jobs.map((job: any) => ({
    id: job.job_id,
    title: job.video_name || job.task?.slice(0, 35) + "...",
    status: job.status,
    date: new Date(job.created_at).toLocaleString(),
    video_url: job.result?.video_url,
    duration: job.result?.duration_seconds ? `${job.result.duration_seconds}s` : "--",
    user_id: job.user_id,
    user_name: job.user_name || null,
    user_status: job.user_status || null,
    user_tier: job.user_tier || null,
    task: job.task || "",
    video_name: job.video_name || "",
    job_type: job.job_type || "",
    config: job.config || {},
    result: job.result || null,
    progress: job.progress || null,
    error: job.error || null,
    cancel_message: job.cancel_message || null,
    cancel_reason_label: job.cancel_reason_label || null,
    cancelled_by_role: job.cancelled_by_role || null,
    cancelled_at: job.cancelled_at || null,
    created_at: job.created_at,
    started_at: job.started_at || null,
    completed_at: job.completed_at || null,
  }));
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const res = await fetch(`${API_BASE}/admin/stats`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch stats");
  return res.json();
}

export async function createAdminUser(
  payload: AdminCreateUserPayload,
): Promise<{ message: string; user: AdminUser }> {
  const res = await fetch(`${API_BASE}/admin/users`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Không thể tạo người dùng");
  }
  return res.json();
}

export async function cancelAdminJob(
  jobId: string,
  reasonCode: string,
): Promise<{
  message: string;
  job_id: string;
  status: VideoStatus;
  reason_label: string;
}> {
  const res = await fetch(`${API_BASE}/admin/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ reason_code: reasonCode }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Không thể dừng job");
  }
  return res.json();
}

export async function updateUserTier(
  userId: string,
  tier: string,
  videosPerMonth?: number,
) {
  const res = await fetch(
    `${API_BASE}/admin/users/${userId}/tier?tier=${tier}${videosPerMonth ? `&videos_per_month=${videosPerMonth}` : ""}`,
    {
      method: "PUT",
      headers: getAuthHeaders(),
    },
  );
  if (!res.ok) throw new Error("Failed to update user tier");
  return res.json();
}

export async function suspendUser(userId: string, reason: string) {
  const res = await fetch(`${API_BASE}/admin/users/${userId}/suspend`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error("Failed to suspend user");
  return res.json();
}

export async function activateUser(userId: string) {
  const res = await fetch(`${API_BASE}/admin/users/${userId}/activate`, {
    method: "PUT",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to activate user");
  return res.json();
}

// Browser Session Management API functions
export interface BrowserSession {
  worker_type: string;
  last_login: string | null;
  days_since_login: number | null;
  needs_refresh: boolean;
  warning_level: "ok" | "warning" | "critical";
}

export interface VNCUrls {
  web: {
    url: string;
    port: number;
    worker: string;
    expires_at?: string;
  };
  presentation: {
    url: string;
    port: number;
    worker: string;
    expires_at?: string;
  };
}

export async function fetchBrowserSessions(): Promise<BrowserSession[]> {
  const res = await fetch(`${API_BASE}/browser/sessions`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch browser sessions");
  return res.json();
}

export async function updateBrowserSession(workerType: string, lastLogin: Date) {
  const res = await fetch(`${API_BASE}/browser/sessions/update`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      worker_type: workerType,
      last_login: lastLogin.toISOString(),
    }),
  });
  if (!res.ok) throw new Error("Failed to update browser session");
  return res.json();
}

export async function fetchVNCUrls(): Promise<VNCUrls> {
  const res = await fetch(`${API_BASE}/browser/vnc-urls`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch VNC URLs");
  return res.json();
}

// Session Manager API functions
export interface SessionStatus {
  status: string;
  message?: string;
  archive_path?: string;
  archive_size?: number;
  last_frozen?: string;
}

export async function fetchSessionStatus(): Promise<SessionStatus> {
  const res = await fetch(`${API_BASE}/session/status`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch session status");
  return res.json();
}

export async function freezeSession(): Promise<SessionStatus> {
  const res = await fetch(`${API_BASE}/session/freeze`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to freeze session");
  }
  return res.json();
}

export interface QueueStatus {
  queues: {
    [key: string]: {
      paused: boolean;
      pause_info?: {
        reason: string;
        paused_at: number;
      };
    };
  };
}

export async function fetchQueueStatus(): Promise<QueueStatus> {
  const res = await fetch(`${API_BASE}/admin/queues/status`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch queue status");
  return res.json();
}

export async function resumeQueue(queueName: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/admin/queues/${queueName}/resume`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to resume queue");
  return res.json();
}

// Agent runtime config (API keys + model name)
// Autoscaler injects these as -e overrides on each `docker compose run`,
// so changes take effect on the NEXT job — no worker rebuild needed.
export interface AgentConfig {
  gemini_api_key: string; // masked unless reveal=true
  gemini_model: string;
  fpt_api_key: string; // masked unless reveal=true
  updated_at: string | null;
  updated_by: string | null;
  supported_models: string[];
  supported_tts_providers: TTSProvider[];
  tts_default_provider: string;
  tts_default_voice: string;
  tts_enabled_providers: string[];
  is_revealed: boolean;
}

export interface TTSVoice {
  id: string;
  label: string;
}

export interface TTSProvider {
  id: string;
  name: string;
  requires_key?: boolean;
  voices: TTSVoice[];
}

export interface PublicTTSOptions {
  providers: TTSProvider[];
  default_provider: string;
  default_voice: string;
}

export async function fetchPublicTTSOptions(): Promise<PublicTTSOptions> {
  const res = await fetch(`${API_BASE}/admin/agent-config/public/tts`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch TTS options");
  return res.json();
}

export async function fetchAgentConfig(reveal = false): Promise<AgentConfig> {
  const res = await fetch(
    `${API_BASE}/admin/agent-config${reveal ? "?reveal=true" : ""}`,
    { headers: getAuthHeaders() },
  );
  if (!res.ok) throw new Error("Failed to fetch agent config");
  return res.json();
}

export async function updateAgentConfig(payload: {
  gemini_api_key?: string;
  gemini_model?: string;
  fpt_api_key?: string;
  tts_default_provider?: string;
  tts_default_voice?: string;
  tts_enabled_providers?: string[];
}): Promise<{
  message: string;
  gemini_api_key: string;
  gemini_model: string;
  fpt_api_key: string;
  updated_at: string;
  updated_by: string;
  note: string;
}> {
  const res = await fetch(`${API_BASE}/admin/agent-config`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to update agent config");
  }
  return res.json();
}

// Quick connectivity tests — let admin verify a key/provider works before
// committing it. Backend hits the upstream service with a tiny request.
export interface TestResult {
  ok: boolean;
  latency_ms: number;
  detail: string;
}

export async function testGemini(payload: {
  api_key?: string;
  model?: string;
}): Promise<TestResult & { model: string }> {
  const res = await fetch(`${API_BASE}/admin/agent-config/gemini/test`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Gemini test failed");
  }
  return res.json();
}

export async function testTTS(payload: {
  provider: string;
  voice?: string;
  api_key?: string;
  text?: string;
}): Promise<
  TestResult & {
    duration_ms: number;
    audio_base64?: string;
    audio_mime?: string;
  }
> {
  const res = await fetch(`${API_BASE}/admin/agent-config/tts/test`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "TTS test failed");
  }
  return res.json();
}

// Google Drive OAuth token (used by presentation-gg-worker for upload).
// Token is generated out-of-band on a dev machine and uploaded here —
// workers never run a browser-based OAuth flow inside the container.
export interface GoogleOAuthStatus {
  exists: boolean;
  valid: boolean;
  expired: boolean;
  has_refresh_token: boolean;
  scopes: string[];
  expiry: string | null;
  token_path: string;
  credentials_file_exists: boolean;
  credentials_path: string;
  warning_level: "ok" | "warning" | "critical" | "missing";
}

export async function fetchGoogleOAuthStatus(): Promise<GoogleOAuthStatus> {
  const res = await fetch(`${API_BASE}/admin/agent-config/google-oauth`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch Google OAuth status");
  return res.json();
}

export async function uploadGoogleOAuthToken(
  file: File,
): Promise<{ message: string; status: GoogleOAuthStatus }> {
  const fd = new FormData();
  fd.append("file", file);
  const token = localStorage.getItem("token");
  const res = await fetch(`${API_BASE}/admin/agent-config/google-oauth/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: fd,
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to upload token");
  }
  return res.json();
}

// Start the Google OAuth web flow. Returns the URL to open in a popup —
// after the user logs in, Google redirects to /callback which closes the
// popup and posts a message back to the opener.
export async function startGoogleOAuthLogin(): Promise<{
  auth_url: string;
  state: string;
  redirect_uri: string;
}> {
  const res = await fetch(`${API_BASE}/admin/agent-config/google-oauth/authorize`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to start OAuth flow");
  }
  return res.json();
}
