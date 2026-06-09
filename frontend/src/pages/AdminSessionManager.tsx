import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchSessionStatus,
  freezeSession,
  fetchQueueStatus,
  resumeQueue,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Monitor,
  Snowflake,
  RefreshCw,
  Loader2,
  Server,
  Clock,
  HardDrive,
  ShieldAlert,
  Play,
  PauseCircle,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const NOVNC_URL =
  import.meta.env.VITE_NOVNC_URL || "/novnc/vnc.html?autoconnect=true&resize=scale";

// Tên hiển thị thân thiện cho từng queue
const QUEUE_LABELS: Record<string, string> = {
  "web-queue": "Web Tutorial",
  "presentation-queue": "Presentation (OneDrive)",
  "presentation-gg-queue": "Presentation (Google)",
  "office-queue": "Office (Slide-to-Video)",
};

export function AdminSessionManager() {
  const queryClient = useQueryClient();

  // Session Manager status
  const {
    data: sessionStatus,
    isLoading: statusLoading,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ["session-status"],
    queryFn: fetchSessionStatus,
    refetchInterval: 30000,
  });

  // Circuit Breaker: Queue pause status
  const {
    data: queueStatus,
    isLoading: queueLoading,
    refetch: refetchQueues,
  } = useQuery({
    queryKey: ["queue-status"],
    queryFn: fetchQueueStatus,
    refetchInterval: 10000,
  });

  const freezeMutation = useMutation({
    mutationFn: freezeSession,
    onSuccess: () => {
      toast.success("Session saved and frozen successfully!");
      refetchStatus();
    },
    onError: (error: Error) => {
      toast.error(`Failed to freeze session: ${error.message}`);
    },
  });

  const resumeMutation = useMutation({
    mutationFn: (queueName: string) => resumeQueue(queueName),
    onSuccess: (_data, queueName) => {
      toast.success(`Queue "${QUEUE_LABELS[queueName] || queueName}" has been resumed!`);
      queryClient.invalidateQueries({ queryKey: ["queue-status"] });
    },
    onError: (error: Error) => {
      toast.error(`Failed to resume queue: ${error.message}`);
    },
  });

  const lastFrozenTime = sessionStatus?.last_frozen
    ? new Date(sessionStatus.last_frozen).toLocaleString("vi-VN")
    : null;

  // Kiểm tra có queue nào đang bị pause không
  const pausedQueues = queueStatus?.queues
    ? Object.entries(queueStatus.queues).filter(([, info]) => info.paused)
    : [];
  const hasPausedQueues = pausedQueues.length > 0;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "ready":
        return <Badge className="bg-emerald-500">Ready</Badge>;
      case "frozen":
        return <Badge className="bg-blue-500">Frozen</Badge>;
      case "unavailable":
        return <Badge className="bg-red-500">Unavailable</Badge>;
      default:
        return <Badge variant="outline">{status || "Unknown"}</Badge>;
    }
  };

  const formatPauseTime = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleString("vi-VN");
  };

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div>
        <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-br from-foreground to-muted-foreground bg-clip-text text-transparent">
          Session Manager
        </h1>
        <p className="text-muted-foreground mt-2 text-lg">
          Log in to Microsoft/Google here, then save & freeze for Workers to use
        </p>
      </div>

      {/* Circuit Breaker Alert */}
      {hasPausedQueues && (
        <Card className="border-2 border-red-500 shadow-lg shadow-red-500/10 bg-red-50 dark:bg-red-950/30 dark:border-red-500/60 animate-in fade-in slide-in-from-top-2 duration-500">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-red-700 dark:text-red-400">
              <ShieldAlert className="w-5 h-5" />
              Circuit Breaker Activated - Session Expired
            </CardTitle>
            <CardDescription className="text-red-600 dark:text-red-400/80">
              One or more queues have been paused because the Chrome session has expired.
              Please log in again in the browser below, then click "Save & Freeze", and
              resume the queues.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {pausedQueues.map(([queueName, info]) => (
                <div
                  key={queueName}
                  className="flex items-center justify-between p-3 bg-white dark:bg-black/40 rounded-lg border border-red-200 dark:border-red-500/20"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <PauseCircle className="w-4 h-4 text-red-500" />
                      <span className="font-semibold text-sm">
                        {QUEUE_LABELS[queueName] || queueName}
                      </span>
                      <Badge className="bg-red-500 text-xs">Paused</Badge>
                    </div>
                    {info.pause_info && (
                      <div className="text-xs text-muted-foreground mt-1 ml-6">
                        <span>Reason: {info.pause_info.reason}</span>
                        {info.pause_info.paused_at && (
                          <span className="ml-3">
                            Since: {formatPauseTime(info.pause_info.paused_at)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-emerald-500 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
                    onClick={() => resumeMutation.mutate(queueName)}
                    disabled={resumeMutation.isPending}
                  >
                    {resumeMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-1" />
                    )}
                    Resume
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Session Status + Queue Status Cards */}
      <div className="grid gap-6 md:grid-cols-4">
        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Server className="w-4 h-4" />
              Session Manager Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            {statusLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              getStatusBadge(sessionStatus?.status || "unavailable")
            )}
            {sessionStatus?.message && (
              <p className="text-xs text-muted-foreground mt-2">
                {sessionStatus.message}
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Clock className="w-4 h-4" />
              Last Frozen
            </CardTitle>
          </CardHeader>
          <CardContent>
            {lastFrozenTime ? (
              <span className="text-lg font-semibold">{lastFrozenTime}</span>
            ) : (
              <span className="text-muted-foreground">Never</span>
            )}
          </CardContent>
        </Card>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <HardDrive className="w-4 h-4" />
              Archive Size
            </CardTitle>
          </CardHeader>
          <CardContent>
            {sessionStatus?.archive_size ? (
              <span className="text-lg font-semibold">
                {(sessionStatus.archive_size / 1024 / 1024).toFixed(2)} MB
              </span>
            ) : (
              <span className="text-muted-foreground">-</span>
            )}
          </CardContent>
        </Card>

        <Card
          className={`border shadow-lg bg-white dark:bg-black/40 dark:backdrop-blur-2xl ${
            hasPausedQueues
              ? "border-red-300 dark:border-red-500/30"
              : "border-gray-200 dark:border-white/10"
          }`}
        >
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <ShieldAlert className="w-4 h-4" />
              Circuit Breaker
            </CardTitle>
          </CardHeader>
          <CardContent>
            {queueLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : hasPausedQueues ? (
              <div className="flex items-center gap-2">
                <Badge className="bg-red-500">
                  {pausedQueues.length} queue(s) paused
                </Badge>
                <AlertTriangle className="w-4 h-4 text-red-500 animate-pulse" />
              </div>
            ) : (
              <Badge className="bg-emerald-500">All queues running</Badge>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Queue Status Detail */}
      {queueStatus?.queues && (
        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldAlert className="w-5 h-5" />
                  Queue Status (Circuit Breaker)
                </CardTitle>
                <CardDescription className="mt-1">
                  When a session expires, the affected queue is automatically paused to
                  prevent repeated failures.
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => refetchQueues()}>
                <RefreshCw className="w-4 h-4 mr-2" />
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(queueStatus.queues).map(([queueName, info]) => (
                <div
                  key={queueName}
                  className={`flex items-center justify-between p-4 rounded-lg border ${
                    info.paused
                      ? "bg-red-50 border-red-200 dark:bg-red-950/20 dark:border-red-500/20"
                      : "bg-gray-50 border-gray-200 dark:bg-white/5 dark:border-white/10"
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      {info.paused ? (
                        <PauseCircle className="w-4 h-4 text-red-500" />
                      ) : (
                        <Play className="w-4 h-4 text-emerald-500" />
                      )}
                      <span className="font-medium text-sm">
                        {QUEUE_LABELS[queueName] || queueName}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground ml-6">
                      {info.paused ? "Paused" : "Running"}
                    </span>
                  </div>
                  {info.paused && (
                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      onClick={() => resumeMutation.mutate(queueName)}
                      disabled={resumeMutation.isPending}
                    >
                      {resumeMutation.isPending ? (
                        <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                      ) : (
                        <Play className="w-4 h-4 mr-1" />
                      )}
                      Resume
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Freeze Action */}
      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Snowflake className="w-5 h-5" />
            Save & Freeze Session
          </CardTitle>
          <CardDescription>
            Safely shut down Chrome and archive the profile. Workers will use this
            archive.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-white/5 rounded-lg">
            <div className="text-sm text-gray-600 dark:text-gray-400">
              <strong>Note:</strong> Make sure you have logged in to the required
              platforms (Microsoft, Google) in the browser below before freezing.
            </div>
            <Button
              onClick={() => freezeMutation.mutate()}
              disabled={freezeMutation.isPending}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {freezeMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Freezing...
                </>
              ) : (
                <>
                  <Snowflake className="w-4 h-4 mr-2" />
                  Save & Freeze
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* noVNC Viewer */}
      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Monitor className="w-5 h-5" />
                Remote Browser (Session Manager)
              </CardTitle>
              <CardDescription className="mt-2">
                Use noVNC to log in to Microsoft/Google. After logging in, press "Save &
                Freeze" above.
              </CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetchStatus()}>
              <RefreshCw className="w-4 h-4 mr-2" />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 rounded-lg p-4">
              <p className="text-sm text-blue-800 dark:text-blue-200">
                <strong>Instructions:</strong> Log in to the required platforms (Microsoft
                365, Google/Gmail...) in this browser. When finished, press the "Save &
                Freeze" button to save the session for Workers.
              </p>
            </div>

            <div className="border border-gray-200 dark:border-white/10 rounded-lg overflow-hidden bg-black">
              <iframe
                src={NOVNC_URL}
                className="w-full h-[600px]"
                title="noVNC - Session Manager"
                allow="clipboard-read; clipboard-write"
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
