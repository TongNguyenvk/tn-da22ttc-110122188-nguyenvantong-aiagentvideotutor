import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import * as z from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { createVideo, fetchPublicTTSOptions } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Loader2,
  Wand2,
  Globe,
  Presentation,
  Monitor,
  FileSpreadsheet,
  FileText,
  Chrome,
  Calculator,
  PaintBucket,
  FileEdit,
} from "lucide-react";
import { useEffect, useState } from "react";

const formSchema = z.object({
  job_type: z.enum(["web", "presentation", "desktop"]),
  prompt: z.string().min(5, { message: "Prompt phải có ít nhất 5 ký tự." }),
  tts_engine: z.string(),
  tts_voice: z.string(),
  padding_ms: z.coerce.number().min(0).max(5000),
  enable_tts: z.boolean(),
  enable_review: z.boolean(),
  // V4 OS Worker fields
  app_type: z.string().optional(),
  browser_url: z.string().optional(),
});

// Supported OS apps for V4
const OS_APPS = [
  { value: "excel", label: "Excel", icon: FileSpreadsheet, category: "office" },
  { value: "word", label: "Word", icon: FileText, category: "office" },
  { value: "powerpoint", label: "PowerPoint", icon: Presentation, category: "office" },
  { value: "chrome", label: "Chrome", icon: Chrome, category: "browser" },
  { value: "edge", label: "Edge", icon: Globe, category: "browser" },
  { value: "firefox", label: "Firefox", icon: Globe, category: "browser" },
  { value: "notepad", label: "Notepad", icon: FileEdit, category: "simple" },
  { value: "calculator", label: "Calculator", icon: Calculator, category: "simple" },
  { value: "paint", label: "Paint", icon: PaintBucket, category: "simple" },
];

export function Create() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);

  // Pull the actual enabled-provider list from backend so this picker
  // reflects whatever admin enabled in Agent Config — no more hardcoded
  // [edge, fpt] tuple that drifts from server reality.
  const { data: ttsOptions } = useQuery({
    queryKey: ["public-tts-options"],
    queryFn: fetchPublicTTSOptions,
    staleTime: 60_000,
  });

  const form = useForm<any>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      job_type: "web",
      prompt: "",
      tts_engine: "",
      tts_voice: "",
      padding_ms: 500,
      enable_tts: true,
      enable_review: true,
      app_type: "",
      browser_url: "",
    },
  });

  const currentJobType = form.watch("job_type");
  const selectedEngine = form.watch("tts_engine");
  const selectedAppType = form.watch("app_type");

  // Seed engine + voice from admin defaults once the options arrive.
  useEffect(() => {
    if (!ttsOptions) return;
    if (!form.getValues("tts_engine") && ttsOptions.default_provider) {
      form.setValue("tts_engine", ttsOptions.default_provider);
      if (ttsOptions.default_voice) {
        form.setValue("tts_voice", ttsOptions.default_voice);
      }
    }
  }, [ttsOptions, form]);

  // Voices for the currently picked provider
  const availableVoices =
    ttsOptions?.providers.find((p) => p.id === selectedEngine)?.voices ?? [];

  // Reset voice when engine changes
  useEffect(() => {
    if (selectedEngine) {
      form.setValue("tts_voice", "");
    }
  }, [selectedEngine, form]);

  const mutation = useMutation({
    mutationFn: createVideo,
    onSuccess: () => {
      toast.success("Đã tạo Job thành công!", {
        description: "Hệ thống đã ghi nhận và đang đưa vào hàng đợi.",
      });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      navigate("/");
    },
    onError: (error: Error) => {
      toast.error("Lỗi mất rồi", {
        description: error.message || "Không thể kết nối với server.",
      });
    },
  });

  function onSubmit(values: z.infer<typeof formSchema>) {
    const finalJobType = values.job_type;

    // Validation for presentation
    if (finalJobType === "presentation" && !file) {
      toast.error("Thiếu file", { description: "Vui lòng chọn file PowerPoint (.pptx)" });
      return;
    }

    // Validation for desktop (OS Worker V4)
    if (finalJobType === "desktop") {
      if (!values.app_type) {
        toast.error("Thiếu thông tin", {
          description: "Vui lòng chọn ứng dụng cần ghi hình",
        });
        return;
      }

      const selectedApp = OS_APPS.find((app) => app.value === values.app_type);

      // Browser apps require URL
      if (selectedApp?.category === "browser" && !values.browser_url) {
        toast.error("Thiếu URL", {
          description: "Vui lòng nhập URL trang web cần mở",
        });
        return;
      }

      // Office apps: File is OPTIONAL (can create new file from scratch)
      // No validation needed - agent can work with or without file
    }

    // Map frontend job_type to backend job_type
    // Frontend uses "desktop" for UX, backend expects "os"
    const backendJobType = finalJobType === "desktop" ? "os" : finalJobType;

    mutation.mutate({
      ...values,
      job_type: backendJobType,
      file: file || undefined,
    });
  }

  const activeType = currentJobType;

  return (
    <div className="max-w-3xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="mb-8">
        <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-primary/50 bg-clip-text text-transparent">
          Tạo Video Mới
        </h1>
        <p className="text-muted-foreground mt-2 text-lg">
          Cung cấp ý tưởng hoặc file trình chiếu, Agent sẽ tự động xử lý.
        </p>
      </div>

      <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
        <CardHeader>
          <CardTitle className="text-gray-900 dark:text-white">
            Cài đặt Pipeline Video
          </CardTitle>
          <CardDescription>
            Thiết lập loại công việc và tham số cho AI Worker
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              <FormField
                control={form.control}
                name="job_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-gray-700 dark:text-zinc-300">
                      Loại Video
                    </FormLabel>
                    <div className="grid grid-cols-3 gap-3 mt-2">
                      <Button
                        type="button"
                        variant={field.value === "web" ? "default" : "outline"}
                        className={`h-20 flex-col gap-2 ${field.value !== "web" && "border-gray-200 bg-gray-50 text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400 dark:hover:text-white dark:hover:bg-white/10"}`}
                        onClick={() => field.onChange("web")}
                      >
                        <Globe className="w-6 h-6" />
                        <span className="text-xs">Web</span>
                      </Button>
                      <Button
                        type="button"
                        variant={field.value === "presentation" ? "default" : "outline"}
                        className={`h-20 flex-col gap-2 ${field.value !== "presentation" && "border-gray-200 bg-gray-50 text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400 dark:hover:text-white dark:hover:bg-white/10"}`}
                        onClick={() => field.onChange("presentation")}
                      >
                        <Presentation className="w-6 h-6" />
                        <span className="text-xs">Trình chiếu</span>
                      </Button>
                      <Button
                        type="button"
                        variant={field.value === "desktop" ? "default" : "outline"}
                        className={`h-20 flex-col gap-2 ${field.value !== "desktop" && "border-gray-200 bg-gray-50 text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400 dark:hover:text-white dark:hover:bg-white/10"}`}
                        onClick={() => field.onChange("desktop")}
                      >
                        <Monitor className="w-6 h-6" />
                        <span className="text-xs">Máy tính</span>
                      </Button>
                    </div>
                  </FormItem>
                )}
              />

              {activeType === "presentation" && (
                <div className="p-4 rounded-lg bg-gray-50 border border-gray-200 border-dashed dark:bg-white/5 dark:border-white/10">
                  <FormLabel className="text-gray-700 dark:text-zinc-300 mb-2 block">
                    Tải lên PowerPoint (.pptx)
                  </FormLabel>
                  <Input
                    type="file"
                    accept=".pptx,.ppt"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="bg-white border-gray-200 text-gray-900 dark:bg-black/50 dark:border-white/10 dark:text-white file:bg-gray-100 file:text-gray-700 dark:file:bg-white/10 dark:file:text-white file:border-0 file:rounded file:px-3 file:py-1 cursor-pointer"
                  />
                  {file && (
                    <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-2">
                      Đã chọn: {file.name}
                    </p>
                  )}
                </div>
              )}

              {/* OS Worker V4 - App Selector */}
              {activeType === "desktop" && (
                <div className="space-y-4 p-4 rounded-lg bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 dark:from-blue-950/20 dark:to-indigo-950/20 dark:border-blue-800/30">
                  <FormField
                    control={form.control}
                    name="app_type"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-gray-900 dark:text-white font-semibold flex items-center gap-2">
                          <Monitor className="w-4 h-4" />
                          Chọn ứng dụng Windows
                        </FormLabel>
                        <div className="grid grid-cols-3 gap-2 mt-2">
                          {OS_APPS.map((app) => {
                            const Icon = app.icon;
                            return (
                              <Button
                                key={app.value}
                                type="button"
                                variant={
                                  field.value === app.value ? "default" : "outline"
                                }
                                className={`h-16 flex-col gap-1 text-xs ${
                                  field.value !== app.value &&
                                  "border-gray-300 bg-white text-gray-700 hover:text-gray-900 hover:bg-gray-50 dark:border-white/20 dark:bg-white/5 dark:text-zinc-300 dark:hover:text-white dark:hover:bg-white/10"
                                }`}
                                onClick={() => {
                                  field.onChange(app.value);
                                  // Reset file and URL when changing app
                                  setFile(null);
                                  form.setValue("browser_url", "");
                                }}
                              >
                                <Icon className="w-5 h-5" />
                                <span>{app.label}</span>
                              </Button>
                            );
                          })}
                        </div>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  {/* File upload for Office apps */}
                  {selectedAppType &&
                    OS_APPS.find((app) => app.value === selectedAppType)?.category ===
                      "office" && (
                      <div className="p-3 rounded-lg bg-white/80 border border-blue-200 dark:bg-black/30 dark:border-blue-700/50">
                        <FormLabel className="text-gray-700 dark:text-zinc-300 mb-2 block text-sm">
                          📎 Upload file{" "}
                          {OS_APPS.find((app) => app.value === selectedAppType)?.label}{" "}
                          (Tùy chọn)
                        </FormLabel>
                        <p className="text-xs text-gray-600 dark:text-gray-400 mb-2">
                          Có thể upload file có sẵn hoặc để trống để tạo file mới
                        </p>
                        <Input
                          type="file"
                          accept={
                            selectedAppType === "excel"
                              ? ".xlsx,.xls,.csv"
                              : selectedAppType === "word"
                                ? ".docx,.doc"
                                : ".pptx,.ppt"
                          }
                          onChange={(e) => setFile(e.target.files?.[0] || null)}
                          className="bg-white border-gray-200 text-gray-900 dark:bg-black/50 dark:border-white/10 dark:text-white file:bg-blue-100 file:text-blue-700 dark:file:bg-blue-900/50 dark:file:text-blue-300 file:border-0 file:rounded file:px-3 file:py-1 cursor-pointer text-sm"
                        />
                        {file && (
                          <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-2 flex items-center gap-1">
                            ✓ Đã chọn: <strong>{file.name}</strong>
                          </p>
                        )}
                      </div>
                    )}

                  {/* URL input for Browser apps */}
                  {selectedAppType &&
                    OS_APPS.find((app) => app.value === selectedAppType)?.category ===
                      "browser" && (
                      <FormField
                        control={form.control}
                        name="browser_url"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-gray-700 dark:text-zinc-300 text-sm">
                              🌐 URL trang web
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder="https://example.com"
                                className="bg-white border-gray-200 text-gray-900 dark:bg-black/50 dark:border-white/10 dark:text-white focus-visible:ring-blue-500"
                                {...field}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}

                  {/* Info for simple apps */}
                  {selectedAppType &&
                    OS_APPS.find((app) => app.value === selectedAppType)?.category ===
                      "simple" && (
                      <div className="p-3 rounded-lg bg-blue-100/50 border border-blue-300 dark:bg-blue-900/20 dark:border-blue-700/50">
                        <p className="text-xs text-blue-800 dark:text-blue-300">
                          ℹ️{" "}
                          <strong>
                            {OS_APPS.find((app) => app.value === selectedAppType)?.label}
                          </strong>{" "}
                          sẽ tự động khởi động. Không cần upload file hay nhập URL.
                        </p>
                      </div>
                    )}
                </div>
              )}

              <FormField
                control={form.control}
                name="prompt"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-gray-700 dark:text-zinc-300">
                      Prompt / Ý tưởng kịch bản
                    </FormLabel>
                    <FormControl>
                      <textarea
                        placeholder={
                          activeType === "presentation"
                            ? "Tùy chọn: Mô tả ngắn gọn nội dung thuyết trình..."
                            : "Ví dụ: Hướng dẫn đăng ký tài khoản GitHub..."
                        }
                        className="w-full bg-white border border-gray-200 text-gray-900 placeholder:text-gray-400 dark:bg-white/5 dark:border-white/10 dark:text-white dark:placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-md p-3 min-h-[100px] resize-y custom-scrollbar"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <FormField
                  control={form.control}
                  name="tts_engine"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-gray-700 dark:text-zinc-300">
                        TTS Engine
                      </FormLabel>
                      <FormControl>
                        <select
                          className="flex h-12 w-full items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary text-gray-900 dark:border-white/10 dark:bg-white/5 dark:text-white"
                          value={field.value}
                          onChange={field.onChange}
                        >
                          <option value="" disabled className="bg-white dark:bg-zinc-900">
                            Chọn TTS Engine
                          </option>
                          {(ttsOptions?.providers ?? []).map((p) => (
                            <option
                              key={p.id}
                              value={p.id}
                              className="bg-white dark:bg-zinc-900"
                            >
                              {p.name}
                              {p.id === ttsOptions?.default_provider ? " (mặc định)" : ""}
                            </option>
                          ))}
                        </select>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="tts_voice"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-gray-700 dark:text-zinc-300">
                        Giọng đọc
                      </FormLabel>
                      <FormControl>
                        <select
                          className="flex h-12 w-full items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary text-gray-900 dark:border-white/10 dark:bg-white/5 dark:text-white"
                          value={field.value}
                          onChange={field.onChange}
                          disabled={!selectedEngine}
                        >
                          <option value="" disabled className="bg-white dark:bg-zinc-900">
                            {!selectedEngine ? "Chọn TTS Engine trước" : "Chọn giọng đọc"}
                          </option>
                          {availableVoices.map((v) => (
                            <option
                              key={v.id}
                              value={v.id}
                              className="bg-white dark:bg-zinc-900"
                            >
                              {v.label}
                            </option>
                          ))}
                        </select>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="padding_ms"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-gray-700 dark:text-zinc-300">
                        Độ trễ (ms)
                      </FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white focus-visible:ring-primary h-12"
                          {...field}
                          value={field.value as number}
                          onChange={(e) => field.onChange(parseInt(e.target.value))}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="flex items-center gap-6 p-4 rounded-lg bg-gray-50 border border-gray-200 dark:bg-white/5 dark:border-white/10">
                <FormField
                  control={form.control}
                  name="enable_tts"
                  render={({ field }) => (
                    <FormItem className="flex items-center space-x-3 space-y-0">
                      <FormControl>
                        <input
                          type="checkbox"
                          className="w-5 h-5 accent-primary"
                          checked={field.value}
                          onChange={field.onChange}
                        />
                      </FormControl>
                      <FormLabel className="text-gray-700 dark:text-zinc-300 font-medium cursor-pointer">
                        Bật Voice (TTS)
                      </FormLabel>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="enable_review"
                  render={({ field }) => (
                    <FormItem className="flex items-center space-x-3 space-y-0">
                      <FormControl>
                        <input
                          type="checkbox"
                          className="w-5 h-5 accent-primary"
                          checked={field.value}
                          onChange={field.onChange}
                        />
                      </FormControl>
                      <FormLabel className="text-gray-700 dark:text-zinc-300 font-medium cursor-pointer">
                        Tạm dừng để Review Kịch Bản
                      </FormLabel>
                    </FormItem>
                  )}
                />
              </div>

              <div className="pt-4 flex justify-end">
                <Button
                  type="submit"
                  size="lg"
                  disabled={mutation.isPending}
                  className="rounded-full shadow-lg shadow-primary/20 w-full sm:w-auto hover:scale-[1.02] active:scale-[0.98] transition-all"
                >
                  {mutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      Đang xử lý Job...
                    </>
                  ) : (
                    <>
                      <Wand2 className="mr-2 h-5 w-5" />
                      Tạo Job
                    </>
                  )}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}
