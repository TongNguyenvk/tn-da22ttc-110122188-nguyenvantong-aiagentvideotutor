import { useEffect, useState } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, CheckCircle2, XCircle, Mail, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

export function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");

  // Resend states
  const [email, setEmail] = useState("");
  const [isResending, setIsResending] = useState(false);
  const [resendSuccess, setResendSuccess] = useState(false);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMessage("Không tìm thấy mã xác thực trong liên kết.");
      return;
    }

    const verifyToken = async () => {
      try {
        const response = await fetch(`/api/auth/verify-email/${token}`);
        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail || "Xác thực thất bại.");
        }
        setStatus("success");
        toast.success("Xác thực email thành công!");
      } catch (err) {
        setStatus("error");
        setErrorMessage(
          err instanceof Error
            ? err.message
            : "Đường dẫn xác thực không hợp lệ hoặc đã hết hạn.",
        );
      }
    };

    verifyToken();
  }, [token]);

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;

    setIsResending(true);
    try {
      const response = await fetch("/api/auth/resend-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Không thể gửi lại email.");
      }

      setResendSuccess(true);
      toast.success("Đã gửi lại email xác thực. Vui lòng kiểm tra hộp thư.");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Có lỗi xảy ra khi gửi lại email.",
      );
    } finally {
      setIsResending(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Mail className="w-10 h-10 text-primary" />
            <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
          </div>
          <p className="text-muted-foreground">Xác thực tài khoản của bạn</p>
        </div>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
          <CardHeader className="text-center">
            {status === "loading" && (
              <>
                <div className="flex justify-center mb-4">
                  <Loader2 className="w-12 h-12 text-primary animate-spin" />
                </div>
                <CardTitle className="text-gray-900 dark:text-white">
                  Đang xác thực
                </CardTitle>
                <CardDescription>
                  Vui lòng chờ trong giây lát, chúng tôi đang kiểm tra mã xác thực của
                  bạn...
                </CardDescription>
              </>
            )}

            {status === "success" && (
              <>
                <div className="flex justify-center mb-4 text-green-500">
                  <CheckCircle2 className="w-16 h-16" />
                </div>
                <CardTitle className="text-gray-900 dark:text-white">
                  Xác thực thành công
                </CardTitle>
                <CardDescription>
                  Email của bạn đã được xác thực. Tài khoản hiện đã sẵn sàng hoạt động.
                </CardDescription>
              </>
            )}

            {status === "error" && (
              <>
                <div className="flex justify-center mb-4 text-red-500">
                  <XCircle className="w-16 h-16" />
                </div>
                <CardTitle className="text-gray-900 dark:text-white">
                  Xác thực thất bại
                </CardTitle>
                <CardDescription className="text-red-500/90 dark:text-red-400/90">
                  {errorMessage}
                </CardDescription>
              </>
            )}
          </CardHeader>

          <CardContent className="space-y-4">
            {status === "success" && (
              <Button onClick={() => navigate("/login")} className="w-full">
                Đăng nhập ngay
              </Button>
            )}

            {status === "error" && (
              <div className="space-y-4">
                {!resendSuccess ? (
                  <form onSubmit={handleResend} className="space-y-4 pt-2">
                    <div className="space-y-2">
                      <Label htmlFor="email" className="text-gray-700 dark:text-gray-300">
                        Nhập email của bạn để nhận lại link xác thực
                      </Label>
                      <Input
                        id="email"
                        type="email"
                        placeholder="your@email.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white"
                      />
                    </div>

                    <Button type="submit" className="w-full" disabled={isResending}>
                      {isResending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Đang gửi lại...
                        </>
                      ) : (
                        "Gửi lại email xác thực"
                      )}
                    </Button>
                  </form>
                ) : (
                  <div className="text-center p-3 rounded-lg bg-green-500/10 border border-green-500/20 text-sm text-green-600 dark:text-green-400">
                    Một liên kết xác thực mới đã được gửi tới email của bạn. Vui lòng kiểm
                    tra hộp thư.
                  </div>
                )}

                <div className="pt-2 flex justify-center">
                  <Link
                    to="/login"
                    className="inline-flex items-center text-sm text-muted-foreground hover:text-primary gap-1"
                  >
                    <ArrowLeft className="w-4 h-4" /> Quay lại đăng nhập
                  </Link>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
