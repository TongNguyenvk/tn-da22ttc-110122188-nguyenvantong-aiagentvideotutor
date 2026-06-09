import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchBrowserSessions,
  fetchVNCUrls,
  updateBrowserSession,
  type BrowserSession,
  type VNCUrls,
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
  AlertTriangle,
  CheckCircle,
  Clock,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";

export function AdminBrowser() {
  const queryClient = useQueryClient();
  const [selectedWorker, setSelectedWorker] = useState<"web" | "presentation">(
    "presentation",
  );
  const [vncUrls, setVncUrls] = useState<VNCUrls | null>(null);

  const {
    data: sessions,
    isLoading: sessionsLoading,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: ["browser-sessions"],
    queryFn: fetchBrowserSessions,
    refetchInterval: 60000, // Refresh every minute
  });

  useEffect(() => {
    fetchVNCUrls().then(setVncUrls).catch(console.error);
  }, []);

  const updateMutation = useMutation({
    mutationFn: ({ workerType, lastLogin }: { workerType: string; lastLogin: Date }) =>
      updateBrowserSession(workerType, lastLogin),
    onSuccess: () => {
      toast.success("Đã cập nhật thời gian đăng nhập");
      queryClient.invalidateQueries({ queryKey: ["browser-sessions"] });
    },
    onError: () => {
      toast.error("Lỗi khi cập nhật thời gian đăng nhập");
    },
  });

  const handleMarkAsLoggedIn = (workerType: string) => {
    updateMutation.mutate({
      workerType,
      lastLogin: new Date(),
    });
  };

  const getSessionForWorker = (workerType: string): BrowserSession | undefined => {
    return sessions?.find((s) => s.worker_type === workerType);
  };

  const webSession = getSessionForWorker("web");
  const presentationSession = getSessionForWorker("presentation");

  const currentVncUrl =
    selectedWorker === "web" ? vncUrls?.web.url : vncUrls?.presentation.url;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div>
        <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-br from-foreground to-muted-foreground bg-clip-text text-transparent">
          Quản lý trình duyệt
        </h1>
        <p className="text-muted-foreground mt-2 text-lg">
          Đăng nhập vào OneDrive/Outlook để duy trì phiên làm việc của worker
        </p>
      </div>

      {/* Session Status Cards */}
      <div className="grid gap-6 md:grid-cols-2">
        <SessionCard
          session={webSession}
          workerType="web"
          workerName="Web Worker"
          isLoading={sessionsLoading}
          onMarkLoggedIn={handleMarkAsLoggedIn}
          onSelect={() => setSelectedWorker("web")}
          isSelected={selectedWorker === "web"}
          isUpdating={updateMutation.isPending}
        />
        <SessionCard
          session={presentationSession}
          workerType="presentation"
          workerName="Presentation Worker"
          isLoading={sessionsLoading}
          onMarkLoggedIn={handleMarkAsLoggedIn}
          onSelect={() => setSelectedWorker("presentation")}
          isSelected={selectedWorker === "presentation"}
          isUpdating={updateMutation.isPending}
        />
      </div>

      {/* noVNC Viewer */}
      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Monitor className="w-5 h-5" />
                Trình duyệt từ xa -{" "}
                {selectedWorker === "web" ? "Web Worker" : "Presentation Worker"}
              </CardTitle>
              <CardDescription className="mt-2">
                Sử dụng noVNC để đăng nhập vào OneDrive/Outlook. Sau khi đăng nhập xong,
                nhấn nút "Đánh dấu đã đăng nhập" bên dưới.
              </CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetchSessions()}>
              <RefreshCw className="w-4 h-4 mr-2" />
              Làm mới
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!vncUrls ? (
            <div className="flex items-center justify-center h-[600px] bg-gray-100 dark:bg-zinc-900 rounded-lg">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 rounded-lg p-4">
                <p className="text-sm text-blue-800 dark:text-blue-200">
                  <strong>Note:</strong> noVNC is served through the Nginx reverse proxy
                  at /novnc/. No SSH tunnel required.
                </p>
              </div>

              <div className="border border-gray-200 dark:border-white/10 rounded-lg overflow-hidden bg-black">
                <iframe
                  src={currentVncUrl}
                  className="w-full h-[600px]"
                  title={`noVNC - ${selectedWorker}`}
                  allow="clipboard-read; clipboard-write"
                />
              </div>

              <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-white/5 rounded-lg">
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Sau khi đăng nhập thành công vào OneDrive/Outlook, nhấn nút bên phải để
                  lưu thời gian đăng nhập.
                </p>
                <Button
                  onClick={() => handleMarkAsLoggedIn(selectedWorker)}
                  disabled={updateMutation.isPending}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {updateMutation.isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Đang lưu...
                    </>
                  ) : (
                    <>
                      <CheckCircle className="w-4 h-4 mr-2" />
                      Đánh dấu đã đăng nhập
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SessionCard({
  session,
  workerType: _workerType,
  workerName,
  isLoading,
  onMarkLoggedIn: _onMarkLoggedIn,
  onSelect,
  isSelected,
  isUpdating: _isUpdating,
}: {
  session?: BrowserSession;
  workerType: string;
  workerName: string;
  isLoading: boolean;
  onMarkLoggedIn: (workerType: string) => void;
  onSelect: () => void;
  isSelected: boolean;
  isUpdating: boolean;
}) {
  if (isLoading) {
    return (
      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-white/5">
        <CardContent className="flex items-center justify-center h-48">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </CardContent>
      </Card>
    );
  }

  const warningLevel = session?.warning_level || "critical";
  const daysSince = session?.days_since_login;
  const lastLogin = session?.last_login
    ? new Date(session.last_login).toLocaleString("vi-VN")
    : "Chưa đăng nhập";

  const borderColor =
    warningLevel === "ok"
      ? "border-emerald-300 dark:border-emerald-500/30"
      : warningLevel === "warning"
        ? "border-yellow-300 dark:border-yellow-500/30"
        : "border-red-300 dark:border-red-500/30";

  const bgColor = isSelected
    ? "bg-primary/5 dark:bg-primary/10"
    : "bg-white dark:bg-white/5";

  return (
    <Card
      className={`border-2 shadow-lg cursor-pointer transition-all hover:shadow-xl ${borderColor} ${bgColor}`}
      onClick={onSelect}
    >
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Monitor className="w-5 h-5" />
            {workerName}
          </span>
          {warningLevel === "ok" && <CheckCircle className="w-5 h-5 text-emerald-500" />}
          {warningLevel === "warning" && (
            <AlertTriangle className="w-5 h-5 text-yellow-500 animate-pulse" />
          )}
          {warningLevel === "critical" && (
            <AlertTriangle className="w-5 h-5 text-red-500 animate-pulse" />
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Lần đăng nhập cuối:
          </span>
        </div>
        <p className="text-lg font-semibold text-gray-900 dark:text-white">{lastLogin}</p>

        {daysSince !== null && daysSince !== undefined && (
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={
                warningLevel === "ok"
                  ? "bg-emerald-50 text-emerald-600 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20"
                  : warningLevel === "warning"
                    ? "bg-yellow-50 text-yellow-600 border-yellow-200 dark:bg-yellow-500/10 dark:text-yellow-400 dark:border-yellow-500/20"
                    : "bg-red-50 text-red-600 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20"
              }
            >
              {daysSince} ngày trước
            </Badge>
          </div>
        )}

        {session?.needs_refresh && (
          <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg p-3">
            <p className="text-sm text-red-800 dark:text-red-200 font-medium">
              ⚠️ Cần đăng nhập lại! Phiên đã quá {daysSince} ngày.
            </p>
          </div>
        )}

        {warningLevel === "warning" && !session?.needs_refresh && (
          <div className="bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/20 rounded-lg p-3">
            <p className="text-sm text-yellow-800 dark:text-yellow-200">
              Sắp hết hạn. Nên đăng nhập lại trong vài ngày tới.
            </p>
          </div>
        )}

        <div className="pt-2">
          <Button
            variant={isSelected ? "default" : "outline"}
            className="w-full"
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
            }}
          >
            {isSelected ? "Đang xem" : "Xem trình duyệt"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
