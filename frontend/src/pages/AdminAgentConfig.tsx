import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchAgentConfig,
  updateAgentConfig,
  fetchGoogleOAuthStatus,
  uploadGoogleOAuthToken,
  startGoogleOAuthLogin,
  testGemini,
  testTTS,
  type AgentConfig,
  type GoogleOAuthStatus,
  type TTSProvider,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Bot,
  Eye,
  EyeOff,
  Loader2,
  Save,
  KeyRound,
  Sparkles,
  Cloud,
  Upload,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  LogIn,
  Mic,
  Play,
  ListChecks,
} from "lucide-react";
import { toast } from "sonner";

// Display copy for each OAuth warning level. Colour pairs are tuned for
// both light and dark themes — the dark variants stay vivid, the light
// variants are deeper hues that don't burn the user's retinas.
const OAUTH_LEVEL_META: Record<
  GoogleOAuthStatus["warning_level"],
  { label: string; tone: string; Icon: typeof CheckCircle2 }
> = {
  ok: {
    label: "Token hợp lệ",
    tone: "border-emerald-500/40 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    Icon: CheckCircle2,
  },
  warning: {
    label: "Token hết hạn — sẽ tự refresh",
    tone: "border-amber-500/40 bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300",
    Icon: AlertTriangle,
  },
  critical: {
    label: "Token hết hạn không refresh được — cần upload lại",
    tone: "border-red-500/40 bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
    Icon: XCircle,
  },
  missing: {
    label: "Chưa có token — job dùng Google Drive sẽ fail",
    tone: "border-red-500/40 bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
    Icon: XCircle,
  },
};

export function AdminAgentConfig() {
  const queryClient = useQueryClient();
  const [revealed, setRevealed] = useState(false);
  const [geminiKey, setGeminiKey] = useState("");
  const [fptKey, setFptKey] = useState("");
  const [model, setModel] = useState("");
  const [dirty, setDirty] = useState(false);
  const oauthFileRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, refetch } = useQuery<AgentConfig>({
    queryKey: ["agent-config", revealed],
    queryFn: () => fetchAgentConfig(revealed),
  });

  // OAuth status — polled separately so an admin can see it go green
  // right after upload without round-tripping the rest of the page.
  const {
    data: oauth,
    isLoading: oauthLoading,
    refetch: refetchOAuth,
  } = useQuery<GoogleOAuthStatus>({
    queryKey: ["google-oauth-status"],
    queryFn: fetchGoogleOAuthStatus,
    refetchInterval: 30000,
  });

  const oauthUpload = useMutation({
    mutationFn: (file: File) => uploadGoogleOAuthToken(file),
    onSuccess: (resp) => {
      toast.success(resp.message);
      queryClient.invalidateQueries({ queryKey: ["google-oauth-status"] });
    },
    onError: (err: Error) => {
      toast.error(err.message);
    },
  });

  // Web OAuth flow: open Google consent screen in a popup, listen for the
  // callback's postMessage, then refetch status.
  const [oauthInProgress, setOauthInProgress] = useState(false);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type !== "google-oauth-result") return;
      setOauthInProgress(false);
      if (e.data.ok) {
        toast.success(e.data.message || "Đăng nhập Google thành công");
        queryClient.invalidateQueries({ queryKey: ["google-oauth-status"] });
      } else {
        toast.error(e.data.message || "Đăng nhập Google thất bại");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [queryClient]);

  const onGoogleLogin = async () => {
    try {
      setOauthInProgress(true);
      const { auth_url } = await startGoogleOAuthLogin();
      const popup = window.open(
        auth_url,
        "google-oauth",
        "width=520,height=720,menubar=no,toolbar=no",
      );
      if (!popup) {
        setOauthInProgress(false);
        toast.error("Popup bị chặn — hãy cho phép popup cho domain này");
        return;
      }
      // If user closes the popup without finishing, clear the in-progress flag
      const tick = setInterval(() => {
        if (popup.closed) {
          clearInterval(tick);
          setOauthInProgress(false);
        }
      }, 500);
    } catch (err) {
      setOauthInProgress(false);
      toast.error((err as Error).message);
    }
  };

  const onPickOAuthFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) oauthUpload.mutate(file);
    e.target.value = "";
  };

  // TTS state — admin chooses default provider + voice + which providers users see
  const [ttsDefaultProvider, setTtsDefaultProvider] = useState<string>("");
  const [ttsDefaultVoice, setTtsDefaultVoice] = useState<string>("");
  const [ttsEnabledProviders, setTtsEnabledProviders] = useState<string[]>([]);

  // Seed the model dropdown + TTS pickers from server once the config loads.
  // Don't clobber values the admin is in the middle of changing.
  useEffect(() => {
    if (!data) return;
    setModel((prev) => (dirty ? prev : data.gemini_model || ""));
    setTtsDefaultProvider((prev) => (dirty ? prev : data.tts_default_provider || "edge"));
    setTtsDefaultVoice((prev) => (dirty ? prev : data.tts_default_voice || ""));
    setTtsEnabledProviders((prev) =>
      dirty ? prev : data.tts_enabled_providers || ["edge"],
    );
  }, [data, dirty]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: {
        gemini_api_key?: string;
        gemini_model?: string;
        fpt_api_key?: string;
        tts_default_provider?: string;
        tts_default_voice?: string;
        tts_enabled_providers?: string[];
      } = {};
      // Only send fields the admin actually typed in. Empty = keep existing.
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
      if (fptKey.trim()) payload.fpt_api_key = fptKey.trim();
      if (model && model !== data?.gemini_model) payload.gemini_model = model;
      if (ttsDefaultProvider && ttsDefaultProvider !== data?.tts_default_provider)
        payload.tts_default_provider = ttsDefaultProvider;
      if (ttsDefaultVoice !== (data?.tts_default_voice ?? ""))
        payload.tts_default_voice = ttsDefaultVoice;
      const prevEnabled = (data?.tts_enabled_providers ?? []).slice().sort().join(",");
      const newEnabled = ttsEnabledProviders.slice().sort().join(",");
      if (newEnabled !== prevEnabled) payload.tts_enabled_providers = ttsEnabledProviders;
      return updateAgentConfig(payload);
    },
    onSuccess: (resp) => {
      toast.success(resp.message);
      setGeminiKey("");
      setFptKey("");
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["agent-config"] });
    },
    onError: (err: Error) => {
      toast.error(err.message);
    },
  });

  const lastUpdated = data?.updated_at
    ? new Date(data.updated_at).toLocaleString("vi-VN")
    : "Chưa từng cập nhật";

  const onToggleReveal = () => {
    setRevealed((v) => !v);
    setDirty(false);
    setGeminiKey("");
    setFptKey("");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Bot className="w-8 h-8 text-primary" />
            Cấu hình Agent
          </h1>
          <p className="text-muted-foreground mt-1">
            API key và model cho con AI agent chạy trong worker. Áp dụng cho job mới —
            không cần build lại worker.
          </p>
        </div>
        <Button variant="outline" onClick={() => refetch()} disabled={isLoading}>
          {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Tải lại"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="w-5 h-5" />
                API Keys
              </CardTitle>
              <CardDescription>
                Trống nghĩa là giữ nguyên giá trị hiện tại. Chỉ ghi đè khi bạn nhập key
                mới.
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onToggleReveal}>
              {revealed ? (
                <>
                  <EyeOff className="w-4 h-4 mr-2" />
                  Ẩn key
                </>
              ) : (
                <>
                  <Eye className="w-4 h-4 mr-2" />
                  Hiển thị key
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="gemini_api_key">
              GEMINI_API_KEY
              <span className="text-muted-foreground font-normal ml-2 text-xs">
                (cho Vision + Planner + Narrator)
              </span>
            </Label>
            <Input
              id="gemini_api_key"
              type={revealed ? "text" : "password"}
              placeholder={
                data?.gemini_api_key
                  ? revealed
                    ? data.gemini_api_key
                    : `Hiện tại: ${data.gemini_api_key} (để trống để giữ)`
                  : "AIza..."
              }
              value={geminiKey}
              onChange={(e) => {
                setGeminiKey(e.target.value);
                setDirty(true);
              }}
              className="font-mono"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="fpt_api_key">
              FPT_API_KEY
              <span className="text-muted-foreground font-normal ml-2 text-xs">
                (cho TTS tiếng Việt)
              </span>
            </Label>
            <Input
              id="fpt_api_key"
              type={revealed ? "text" : "password"}
              placeholder={
                data?.fpt_api_key
                  ? revealed
                    ? data.fpt_api_key
                    : `Hiện tại: ${data.fpt_api_key} (để trống để giữ)`
                  : "FPT API key"
              }
              value={fptKey}
              onChange={(e) => {
                setFptKey(e.target.value);
                setDirty(true);
              }}
              className="font-mono"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5" />
            Model Gemini
          </CardTitle>
          <CardDescription>
            Tất cả pipeline (vision, parser, planner, narrator) sẽ dùng model này thông
            qua biến môi trường <code className="text-xs">GEMINI_MODEL</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="gemini_model">GEMINI_MODEL</Label>
          <select
            id="gemini_model"
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              setDirty(true);
            }}
            className="w-full h-9 rounded-lg border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          >
            <option value="" disabled>
              -- Chọn model --
            </option>
            {(data?.supported_models || []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          {data?.gemini_model && (
            <p className="text-sm text-muted-foreground">
              Đang dùng:{" "}
              <Badge variant="outline" className="font-mono">
                {data.gemini_model}
              </Badge>
            </p>
          )}

          <GeminiTestButton apiKey={geminiKey} model={model} />
        </CardContent>
      </Card>

      <TTSConfigCard
        providers={data?.supported_tts_providers ?? []}
        enabledIds={ttsEnabledProviders}
        defaultProvider={ttsDefaultProvider}
        defaultVoice={ttsDefaultVoice}
        fptKey={fptKey}
        onEnabledChange={(next) => {
          setTtsEnabledProviders(next);
          setDirty(true);
        }}
        onDefaultProviderChange={(p) => {
          setTtsDefaultProvider(p);
          setDirty(true);
        }}
        onDefaultVoiceChange={(v) => {
          setTtsDefaultVoice(v);
          setDirty(true);
        }}
      />

      <Card>
        <CardContent className="pt-6 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            <div>
              Cập nhật lần cuối: <span className="text-foreground">{lastUpdated}</span>
            </div>
            {data?.updated_by && (
              <div>
                Bởi: <span className="text-foreground">{data.updated_by}</span>
              </div>
            )}
          </div>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!dirty || saveMutation.isPending}
            size="lg"
          >
            {saveMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Save className="w-4 h-4 mr-2" />
            )}
            Lưu cấu hình
          </Button>
        </CardContent>
      </Card>

      <GoogleOAuthCard
        status={oauth}
        loading={oauthLoading}
        uploading={oauthUpload.isPending}
        oauthInProgress={oauthInProgress}
        onRefresh={() => refetchOAuth()}
        onPickFile={() => oauthFileRef.current?.click()}
        onLoginWithGoogle={onGoogleLogin}
      />
      <input
        ref={oauthFileRef}
        type="file"
        accept=".pickle,application/octet-stream"
        className="hidden"
        onChange={onPickOAuthFile}
      />
    </div>
  );
}

function GoogleOAuthCard({
  status,
  loading,
  uploading,
  oauthInProgress,
  onRefresh,
  onPickFile,
  onLoginWithGoogle,
}: {
  status: GoogleOAuthStatus | undefined;
  loading: boolean;
  uploading: boolean;
  oauthInProgress: boolean;
  onRefresh: () => void;
  onPickFile: () => void;
  onLoginWithGoogle: () => void;
}) {
  const level = status?.warning_level ?? "missing";
  const meta = OAUTH_LEVEL_META[level];
  const Icon = meta.Icon;

  const expiryDisplay = status?.expiry
    ? new Date(status.expiry).toLocaleString("vi-VN")
    : "—";

  return (
    <Card className={meta.tone.split(" ").slice(0, 2).join(" ")}>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Cloud className="w-5 h-5" />
              Google Drive OAuth
            </CardTitle>
            <CardDescription>
              Token đăng nhập Google cho worker upload Slides. Đăng nhập ngay từ admin UI
              — KHÔNG cần SSH vào VPS.
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Kiểm tra lại"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${meta.tone}`}
        >
          <Icon className="w-5 h-5 shrink-0" />
          <div className="text-sm font-medium">{meta.label}</div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="space-y-1">
            <div className="text-muted-foreground">Token file</div>
            <div className="font-mono text-xs break-all">{status?.token_path || "—"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-muted-foreground">Credentials JSON</div>
            <div className="flex items-center gap-2">
              {status?.credentials_file_exists ? (
                <Badge
                  variant="outline"
                  className="text-emerald-700 border-emerald-500/40 dark:text-emerald-300"
                >
                  Có sẵn
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="text-red-700 border-red-500/40 dark:text-red-300"
                >
                  Thiếu — không refresh được
                </Badge>
              )}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-muted-foreground">Hết hạn</div>
            <div>{expiryDisplay}</div>
          </div>
          <div className="space-y-1">
            <div className="text-muted-foreground">Refresh token</div>
            <div>{status?.has_refresh_token ? "Có" : "Không"}</div>
          </div>
          <div className="space-y-1 col-span-2">
            <div className="text-muted-foreground">Scopes</div>
            <div className="flex flex-wrap gap-1">
              {(status?.scopes || []).length === 0 ? (
                <span className="text-muted-foreground text-xs">—</span>
              ) : (
                status?.scopes.map((s) => (
                  <Badge key={s} variant="outline" className="font-mono text-xs">
                    {s.replace("https://www.googleapis.com/auth/", "")}
                  </Badge>
                ))
              )}
            </div>
          </div>
        </div>

        <Button
          onClick={onLoginWithGoogle}
          disabled={oauthInProgress}
          className="w-full"
          size="lg"
        >
          {oauthInProgress ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <LogIn className="w-4 h-4 mr-2" />
          )}
          Đăng nhập với Google
        </Button>

        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground select-none">
            Hoặc upload file .pickle có sẵn (cách cũ, cần CLI)
          </summary>
          <div className="mt-3 space-y-3 rounded-lg border border-muted bg-muted/30 p-3">
            <ol className="list-decimal list-inside space-y-1">
              <li>
                Trên máy có browser, chạy:{" "}
                <code className="px-1.5 py-0.5 rounded bg-background border">
                  python webreel-ai-agent/refresh_google_oauth_token.py
                </code>
              </li>
              <li>
                Hoàn tất đăng nhập, script lưu file{" "}
                <code className="px-1.5 py-0.5 rounded bg-background border">
                  google_oauth_token.pickle
                </code>
                .
              </li>
              <li>Bấm nút bên dưới và chọn file vừa sinh.</li>
            </ol>
            <Button
              onClick={onPickFile}
              disabled={uploading}
              variant="outline"
              className="w-full"
            >
              {uploading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Upload className="w-4 h-4 mr-2" />
              )}
              Upload token (.pickle)
            </Button>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

// Small inline button that pings the saved Gemini config (or the values the
// admin is currently typing, if non-empty). Shows a one-line result so the
// admin sees a wrong key immediately instead of on the next job.
function GeminiTestButton({ apiKey, model }: { apiKey: string; model: string }) {
  const [result, setResult] = useState<{
    ok: boolean;
    detail: string;
    latency_ms: number;
  } | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      testGemini({
        api_key: apiKey.trim() || undefined,
        model: model.trim() || undefined,
      }),
    onSuccess: (resp) => setResult(resp),
    onError: (err: Error) => {
      setResult({ ok: false, detail: err.message, latency_ms: 0 });
    },
  });

  return (
    <div className="space-y-2 pt-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setResult(null);
          mutation.mutate();
        }}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? (
          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        ) : (
          <ListChecks className="w-4 h-4 mr-2" />
        )}
        Test key + model
      </Button>
      {result && (
        <div
          className={`text-xs px-3 py-2 rounded-lg border ${
            result.ok
              ? "border-emerald-500/40 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
              : "border-red-500/40 bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300"
          }`}
        >
          {result.ok ? "✓" : "✗"} {result.detail}
          {result.latency_ms ? ` (${result.latency_ms}ms)` : ""}
        </div>
      )}
    </div>
  );
}

// Admin controls for which TTS providers users can pick on the Create form,
// plus the system-wide default. Includes per-provider Test buttons that
// stream a tiny mp3 back so the admin can listen before saving.
function TTSConfigCard({
  providers,
  enabledIds,
  defaultProvider,
  defaultVoice,
  fptKey,
  onEnabledChange,
  onDefaultProviderChange,
  onDefaultVoiceChange,
}: {
  providers: TTSProvider[];
  enabledIds: string[];
  defaultProvider: string;
  defaultVoice: string;
  // Live value of the FPT key field — used for "test before save".
  fptKey: string;
  onEnabledChange: (next: string[]) => void;
  onDefaultProviderChange: (id: string) => void;
  onDefaultVoiceChange: (voice: string) => void;
}) {
  const defaultProviderMeta = providers.find((p) => p.id === defaultProvider);
  const voicesForDefault = defaultProviderMeta?.voices ?? [];

  const toggleProvider = (id: string, on: boolean) => {
    const next = new Set(enabledIds);
    if (on) next.add(id);
    else next.delete(id);
    // Edge always stays enabled — losing it strands free-tier users with
    // no working TTS. Server enforces this too.
    next.add("edge");
    onEnabledChange(Array.from(next));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mic className="w-5 h-5" />
          TTS Provider
        </CardTitle>
        <CardDescription>
          Provider hiện đang dùng:{" "}
          <Badge variant="outline" className="font-mono">
            edge
          </Badge>{" "}
          (Edge TTS, miễn phí). Bật thêm provider nào ở đây thì user mới thấy được trong
          form Tạo Job.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div>
          <Label className="mb-2 block">Provider được phép sử dụng</Label>
          <div className="space-y-2">
            {providers.map((p) => {
              const checked = enabledIds.includes(p.id);
              const isEdge = p.id === "edge";
              return (
                <label
                  key={p.id}
                  className="flex items-start gap-3 p-3 rounded-lg border border-input hover:bg-muted/30 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={isEdge}
                    onChange={(e) => toggleProvider(p.id, e.target.checked)}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-sm">
                      {p.name}
                      {p.requires_key && (
                        <Badge
                          variant="outline"
                          className="ml-2 text-xs text-yellow-400 border-yellow-500/30"
                        >
                          cần API key
                        </Badge>
                      )}
                      {isEdge && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          (luôn bật)
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {p.voices.length} giọng đọc
                    </div>
                  </div>
                  <TTSTestInline
                    providerId={p.id}
                    voice={p.voices[0]?.id}
                    fptKeyOverride={p.id === "fpt" ? fptKey : ""}
                  />
                </label>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="tts_default_provider">Provider mặc định</Label>
            <select
              id="tts_default_provider"
              value={defaultProvider}
              onChange={(e) => {
                onDefaultProviderChange(e.target.value);
                // Reset voice when provider changes
                onDefaultVoiceChange("");
              }}
              className="w-full h-9 rounded-lg border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            >
              {providers
                .filter((p) => enabledIds.includes(p.id))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="tts_default_voice">Giọng mặc định</Label>
            <select
              id="tts_default_voice"
              value={defaultVoice}
              onChange={(e) => onDefaultVoiceChange(e.target.value)}
              disabled={!voicesForDefault.length}
              className="w-full h-9 rounded-lg border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 disabled:opacity-50"
            >
              <option value="">(không chỉ định — user chọn)</option>
              {voicesForDefault.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Small Test button that lives in the per-provider row. Generates a sample
// mp3 and plays it back via an <audio> element so admin can actually hear
// the voice — base64-encoded blob keeps the request/response single-shot.
function TTSTestInline({
  providerId,
  voice,
  fptKeyOverride,
}: {
  providerId: string;
  voice?: string;
  // For FPT: live value of the key field on this same page, so admin can
  // verify a freshly-typed key without saving first.
  fptKeyOverride: string;
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      testTTS({
        provider: providerId,
        voice,
        api_key: providerId === "fpt" ? fptKeyOverride.trim() || undefined : undefined,
      }),
    onSuccess: (resp) => {
      if (!resp.ok) {
        setError(resp.detail);
        setAudioUrl(null);
        return;
      }
      if (resp.audio_base64) {
        const blob = base64ToBlob(resp.audio_base64, resp.audio_mime || "audio/mpeg");
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);
        setError(null);
      }
    },
    onError: (err: Error) => {
      setError(err.message);
      setAudioUrl(null);
    },
  });

  // Don't leak blob: URLs across re-tests
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  return (
    <div className="flex flex-col items-end gap-1" onClick={(e) => e.preventDefault()}>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => {
          setError(null);
          mutation.mutate();
        }}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? (
          <Loader2 className="w-4 h-4" />
        ) : (
          <Play className="w-4 h-4" />
        )}
      </Button>
      {audioUrl && (
        <audio
          src={audioUrl}
          controls
          autoPlay
          className="h-8"
          style={{ maxWidth: 220 }}
        />
      )}
      {error && (
        <span
          className="text-xs text-red-700 dark:text-red-300 max-w-[220px] truncate"
          title={error}
        >
          ✗ {error}
        </span>
      )}
    </div>
  );
}

function base64ToBlob(b64: string, mime: string): Blob {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}
