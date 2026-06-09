import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  PlayCircle,
  Plus,
  LayoutGrid,
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCcw,
  FileEdit,
  Download,
  Eye,
  X,
  Info,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchVideos,
  getJobDetail,
  getVideoDownloadUrl,
  getVideoViewUrl,
} from "@/lib/api";
import type { JobDetail } from "@/lib/api";
import { useState, useCallback } from "react";
import { Phase25Review } from "@/components/Phase25Review";
import { toast } from "sonner";

export function Dashboard() {
  const [reviewingJobId, setReviewingJobId] = useState<string | null>(null);
  const [detailJob, setDetailJob] = useState<JobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const {
    data: videos,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["videos"],
    queryFn: fetchVideos,
    refetchInterval: 5000,
  });

  const displayVideos = videos || [];

  const totalCompleted = displayVideos.filter((v) => v.status === "completed").length;
  const successRate =
    displayVideos.length > 0
      ? ((totalCompleted / displayVideos.length) * 100).toFixed(1)
      : "100.0";
  const totalProcessing = displayVideos.filter((v) =>
    ["pending", "queued", "running", "processing"].includes(v.status),
  ).length;
  const totalPendingReview = displayVideos.filter(
    (v) => v.status === "pending_review",
  ).length;

  const openJobDetail = useCallback(async (jobId: string) => {
    setDetailLoading(true);
    try {
      const detail = await getJobDetail(jobId);
      setDetailJob(detail);
    } catch {
      toast.error("Không thể tải chi tiết job");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleDownload = useCallback((jobId: string, videoName?: string) => {
    const url = getVideoDownloadUrl(jobId);
    const token = localStorage.getItem("token");
    if (token) {
      fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((res) => {
          if (!res.ok) throw new Error("Download failed");
          return res.blob();
        })
        .then((blob) => {
          const blobUrl = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = blobUrl;
          link.download = videoName ? `${videoName}.mp4` : "video.mp4";
          link.click();
          URL.revokeObjectURL(blobUrl);
          toast.success("Tải video thành công!");
        })
        .catch(() => toast.error("Lỗi khi tải video"));
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = videoName ? `${videoName}.mp4` : "video.mp4";
      a.click();
    }
  }, []);

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-br from-foreground to-muted-foreground bg-clip-text text-transparent">
            Tổng quan
          </h1>
          <p className="text-muted-foreground mt-2 text-lg">
            {"Hệ thống quản trị và giám sát trạng thái render video."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isFetching && (
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          )}
          <Link
            to="/create"
            className={buttonVariants({
              size: "lg",
              className:
                "rounded-full shadow-lg shadow-primary/20 transition-all hover:scale-105 active:scale-95",
            })}
          >
            <Plus className="mr-2 h-5 w-5" />
            {"Tạo Video Mới"}
          </Link>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-4">
        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-white/5 dark:backdrop-blur-xl">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-600 dark:text-gray-400">
              {"Tổng Video"}
            </CardTitle>
            <LayoutGrid className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-gray-900 dark:text-white">
              {displayVideos.length}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {"Tất cả các job"}
            </p>
          </CardContent>
        </Card>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-white/5 dark:backdrop-blur-xl">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-600 dark:text-gray-400">
              {"Đang xử lý"}
            </CardTitle>
            <Clock className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-gray-900 dark:text-white">
              {totalProcessing}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {"Đang chạy pipeline"}
            </p>
          </CardContent>
        </Card>

        <Card
          className={`border shadow-lg bg-white dark:bg-white/5 dark:backdrop-blur-xl ${totalPendingReview > 0 ? "border-blue-300 dark:border-blue-500/30 ring-2 ring-blue-500/20" : "border-gray-200 dark:border-white/10"}`}
        >
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-600 dark:text-gray-400">
              {"Chờ Review"}
            </CardTitle>
            <FileEdit
              className={`h-4 w-4 ${totalPendingReview > 0 ? "text-blue-500 animate-pulse" : "text-blue-400"}`}
            />
          </CardHeader>
          <CardContent>
            <div
              className={`text-4xl font-bold ${totalPendingReview > 0 ? "text-blue-600 dark:text-blue-400" : "text-gray-900 dark:text-white"}`}
            >
              {totalPendingReview}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {totalPendingReview > 0 ? "Cần duyệt kịch bản TTS" : "Không có job nào"}
            </p>
          </CardContent>
        </Card>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-white/5 dark:backdrop-blur-xl">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-600 dark:text-gray-400">
              {"Tỷ lệ thành công"}
            </CardTitle>
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-gray-900 dark:text-white">
              {successRate}%
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {"Thống kê toàn thời gian"}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-2xl overflow-hidden rounded-2xl">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              {"Video gần đây"}
            </h2>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCcw className="w-4 h-4 mr-2" />
              {"Làm mới"}
            </Button>
          </div>

          <div className="rounded-lg border border-gray-200 dark:border-white/10 overflow-hidden shadow-sm">
            <Table>
              <TableHeader className="bg-gray-50/50 dark:bg-white/5 border-b border-gray-200 dark:border-white/10">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[80px] bg-transparent font-semibold text-gray-700 dark:text-gray-300">
                    Media
                  </TableHead>
                  <TableHead className="bg-transparent font-semibold text-gray-700 dark:text-gray-300">
                    {"Tiêu đề"}
                  </TableHead>
                  <TableHead className="bg-transparent font-semibold text-gray-700 dark:text-gray-300">
                    {"Trạng thái"}
                  </TableHead>
                  <TableHead className="bg-transparent font-semibold text-gray-700 dark:text-gray-300">
                    {"Thời lượng"}
                  </TableHead>
                  <TableHead className="text-right bg-transparent font-semibold text-gray-700 dark:text-gray-300">
                    {"Hành động"}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="bg-white dark:bg-transparent">
                {isLoading ? (
                  <TableRow className="bg-white dark:bg-transparent">
                    <TableCell
                      colSpan={5}
                      className="h-32 text-center text-muted-foreground"
                    >
                      <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />
                      {"Đang lấy dữ liệu từ API..."}
                    </TableCell>
                  </TableRow>
                ) : displayVideos.length === 0 ? (
                  <TableRow className="bg-white dark:bg-transparent">
                    <TableCell
                      colSpan={5}
                      className="h-32 text-center text-muted-foreground"
                    >
                      {"Chưa có video nào. Hãy tạo video mới!"}
                    </TableCell>
                  </TableRow>
                ) : (
                  displayVideos.map((video) => (
                    <TableRow
                      key={video.id}
                      className="border-b border-gray-100 dark:border-white/5 hover:bg-gray-50/50 dark:hover:bg-white/5 transition-colors group bg-white dark:bg-transparent cursor-pointer"
                      onClick={() => openJobDetail(String(video.id))}
                    >
                      <TableCell>
                        <div className="h-12 w-20 rounded bg-zinc-800/80 overflow-hidden relative border border-white/10 group-hover:border-primary/50 transition-colors flex items-center justify-center">
                          {video.thumbnail ? (
                            <>
                              <img
                                src={video.thumbnail}
                                alt={video.title}
                                className="w-full h-full object-cover opacity-80"
                              />
                              <PlayCircle className="absolute w-6 h-6 text-white drop-shadow-md opacity-0 group-hover:opacity-100 transition-opacity" />
                            </>
                          ) : (
                            <div className="flex items-center justify-center w-full h-full text-zinc-600">
                              {video.status === "completed" ? (
                                <PlayCircle className="w-5 h-5 text-emerald-500/70" />
                              ) : video.status === "pending_review" ? (
                                <FileEdit className="w-5 h-5 animate-bounce text-blue-400" />
                              ) : ["pending", "queued", "running", "processing"].includes(
                                  video.status,
                                ) ? (
                                <Clock className="w-5 h-5 animate-pulse text-yellow-500/70" />
                              ) : (
                                <AlertCircle className="w-5 h-5 text-red-500/70" />
                              )}
                            </div>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="font-medium text-base text-gray-900 dark:text-zinc-200">
                        {video.title}
                        <span className="block text-xs text-gray-500 dark:text-muted-foreground mt-1 font-normal opacity-70">
                          {video.date}
                        </span>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={video.status} />
                      </TableCell>
                      <TableCell className="text-gray-600 dark:text-muted-foreground font-mono">
                        {video.duration || "--"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div
                          className="flex items-center justify-end gap-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {video.status === "pending_review" && (
                            <Button
                              size="sm"
                              className="bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-500/20"
                              onClick={() => setReviewingJobId(String(video.id))}
                            >
                              <FileEdit className="w-4 h-4 mr-1" />
                              Review
                            </Button>
                          )}

                          {video.status === "completed" && (
                            <>
                              {video.video_url && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20"
                                  onClick={async () => {
                                    try {
                                      const url = await getVideoViewUrl(String(video.id));
                                      window.open(url, "_blank", "noopener,noreferrer");
                                    } catch (e) {
                                      toast.error((e as Error).message);
                                    }
                                  }}
                                >
                                  <Eye className="w-4 h-4 mr-1" />
                                  Xem
                                </Button>
                              )}
                              <Button
                                size="sm"
                                className="bg-primary hover:bg-primary/90 text-white shadow-lg shadow-primary/20"
                                onClick={() =>
                                  handleDownload(String(video.id), video.title)
                                }
                              >
                                <Download className="w-4 h-4 mr-1" />
                                {"Tải xuống"}
                              </Button>
                            </>
                          )}

                          {["failed", "cancelled"].includes(video.status) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-zinc-400 hover:text-white"
                              onClick={() => openJobDetail(String(video.id))}
                            >
                              <Info className="w-4 h-4 mr-1" />
                              {"Chi tiết"}
                            </Button>
                          )}

                          {["pending", "queued", "running", "processing"].includes(
                            video.status,
                          ) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-zinc-400"
                              disabled
                            >
                              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                              {"Đang xử lý"}
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      </Card>

      {reviewingJobId && (
        <Phase25Review
          jobId={reviewingJobId}
          onApprove={() => {
            setReviewingJobId(null);
            refetch();
          }}
          onClose={() => setReviewingJobId(null)}
        />
      )}

      {(detailJob || detailLoading) && (
        <JobDetailDialog
          job={detailJob}
          loading={detailLoading}
          onClose={() => setDetailJob(null)}
          onReview={(jobId) => {
            setDetailJob(null);
            setReviewingJobId(jobId);
          }}
          onDownload={(jobId, name) => handleDownload(jobId, name)}
        />
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, { text: string; style: string }> = {
    completed: {
      text: "Hoàn thành",
      style: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    },
    pending_review: {
      text: "Chờ Review (2.5)",
      style: "bg-blue-500/20 text-blue-400 border-blue-500/30 animate-pulse",
    },
    failed: { text: "Thất bại", style: "bg-red-500/10 text-red-400 border-red-500/20" },
    cancelled: { text: "Đã hủy", style: "bg-red-500/10 text-red-400 border-red-500/20" },
  };
  const info = labels[status] || {
    text: "Đang xử lý",
    style: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20 animate-pulse",
  };
  return (
    <Badge variant="outline" className={`${info.style} px-3 py-1 font-medium`}>
      {info.text}
    </Badge>
  );
}

function JobDetailDialog({
  job,
  loading,
  onClose,
  onReview,
  onDownload,
}: {
  job: JobDetail | null;
  loading: boolean;
  onClose: () => void;
  onReview: (jobId: string) => void;
  onDownload: (jobId: string, name?: string) => void;
}) {
  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="bg-zinc-950 border border-white/10 p-8 rounded-xl flex flex-col items-center">
          <Loader2 className="w-8 h-8 animate-spin text-primary mb-4" />
          <p className="text-zinc-300">{"Đang tải chi tiết..."}</p>
        </div>
      </div>
    );
  }

  if (!job) return null;

  const phaseNames: Record<number, string> = {
    1: "Scout (browser-use)",
    2: "Parser (config + tts)",
    2.5: "Review kịch bản TTS",
    3: "Tạo âm thanh TTS",
    4: "Injector (nhúng pause)",
    5: "Ghi hình (Webreel record)",
    6: "Composer (ffmpeg sync)",
  };

  const currentPhase = job.progress?.current_phase;

  // Sort phases in correct order (1, 2, 2.5, 3, 4, 5, 6)
  const sortedPhases = Object.entries(phaseNames).sort(
    ([a], [b]) => parseFloat(a) - parseFloat(b),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-zinc-950 border border-gray-200 dark:border-white/10 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5">
          <div>
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">
              {"Chi tiết Job"}
            </h2>
            <p className="text-sm text-gray-500 dark:text-zinc-400 mt-0.5 font-mono">
              {job.job_id}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-200 dark:hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-gray-900 dark:hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500 dark:text-zinc-400 w-24 shrink-0">
              {"Trạng thái:"}
            </span>
            <StatusBadge status={job.status} />
          </div>

          <div>
            <span className="text-sm text-gray-500 dark:text-zinc-400 block mb-1">
              {"Nội dung:"}
            </span>
            <p className="text-sm text-gray-900 dark:text-zinc-200 bg-gray-100 dark:bg-white/5 rounded-lg p-3 border border-gray-200 dark:border-white/10">
              {job.task}
            </p>
          </div>

          {currentPhase !== undefined && currentPhase !== null && (
            <div>
              <span className="text-sm text-gray-500 dark:text-zinc-400 block mb-2">
                {"Tiến trình Pipeline:"}
              </span>
              <div className="space-y-2">
                {sortedPhases.map(([phaseStr, name]) => {
                  const phase = parseFloat(phaseStr);
                  // When job is completed, no phase should be active
                  const isCompleted =
                    job.status === "completed" ? true : currentPhase > phase;
                  const isActive =
                    job.status === "completed" ? false : currentPhase === phase;
                  return (
                    <div
                      key={phaseStr}
                      className={`flex items-center gap-3 text-sm px-3 py-2 rounded-lg transition-colors ${
                        isActive
                          ? "bg-primary/10 border border-primary/30 text-primary font-medium"
                          : isCompleted
                            ? "text-emerald-500 dark:text-emerald-400"
                            : "text-gray-400 dark:text-zinc-600"
                      }`}
                    >
                      {isCompleted ? (
                        <CheckCircle2 className="w-4 h-4 shrink-0" />
                      ) : isActive ? (
                        <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border-2 border-current shrink-0" />
                      )}
                      <span>
                        Phase {phaseStr}: {name}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {job.error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
              <span className="text-sm font-medium text-red-400 block mb-1">
                {"Lỗi:"}
              </span>
              <p className="text-sm text-red-300">{job.error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-500 dark:text-zinc-500 block">{"Tạo lúc:"}</span>
              <span className="text-gray-900 dark:text-zinc-300">
                {new Date(job.created_at).toLocaleString()}
              </span>
            </div>
            {job.started_at && (
              <div>
                <span className="text-gray-500 dark:text-zinc-500 block">
                  {"Bắt đầu:"}
                </span>
                <span className="text-gray-900 dark:text-zinc-300">
                  {new Date(job.started_at).toLocaleString()}
                </span>
              </div>
            )}
            {job.completed_at && (
              <div>
                <span className="text-gray-500 dark:text-zinc-500 block">
                  {"Hoàn thành:"}
                </span>
                <span className="text-gray-900 dark:text-zinc-300">
                  {new Date(job.completed_at).toLocaleString()}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 flex items-center justify-between">
          <Button
            variant="ghost"
            className="text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-white"
            onClick={onClose}
          >
            {"Đóng"}
          </Button>
          <div className="flex gap-2">
            {job.status === "pending_review" && (
              <Button
                className="bg-blue-600 hover:bg-blue-700 text-white"
                onClick={() => onReview(job.job_id)}
              >
                <FileEdit className="w-4 h-4 mr-2" />
                {"Review kịch bản"}
              </Button>
            )}
            {job.status === "completed" && (
              <Button
                className="bg-primary hover:bg-primary/90 text-white"
                onClick={() => onDownload(job.job_id, job.video_name)}
              >
                <Download className="w-4 h-4 mr-2" />
                {"Tải Video"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
