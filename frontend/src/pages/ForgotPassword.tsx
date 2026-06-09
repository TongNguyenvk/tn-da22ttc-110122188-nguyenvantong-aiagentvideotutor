import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { Loader2, KeyRound, AlertCircle, CheckCircle2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

export function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [isGoogleUser, setIsGoogleUser] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setIsGoogleUser(false);

    try {
      const response = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        const detail = errorData.detail || "";

        if (
          detail.includes("Google") ||
          detail.includes("google") ||
          detail.includes("Google Sign-In")
        ) {
          setIsGoogleUser(true);
          toast.error("Tài khoản sử dụng Google Sign-In.");
          return;
        }

        throw new Error(detail || "Có lỗi xảy ra khi gửi yêu cầu.");
      }

      setIsSuccess(true);
      toast.success("Đã gửi liên kết đặt lại mật khẩu thành công!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Có lỗi xảy ra khi gửi yêu cầu.");
    } finally {
      setIsLoading(false);
    }
  };

  if (isSuccess) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <div className="flex items-center justify-center gap-2 mb-4">
              <KeyRound className="w-10 h-10 text-primary" />
              <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
            </div>
          </div>

          <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
            <CardHeader className="text-center">
              <div className="flex justify-center mb-4 text-green-500">
                <CheckCircle2 className="w-16 h-16 animate-bounce" />
              </div>
              <CardTitle className="text-gray-900 dark:text-white">
                Kiểm tra email của bạn
              </CardTitle>
              <CardDescription>
                Nếu tài khoản tồn tại trên hệ thống, một hướng dẫn đặt lại mật khẩu đã
                được gửi đến:
              </CardDescription>
              <p className="font-semibold text-gray-900 dark:text-white mt-1">{email}</p>
            </CardHeader>
            <CardContent className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">
                Vui lòng kiểm tra hộp thư (và cả thư rác/spam) và nhấp vào liên kết để tạo
                mật khẩu mới.
              </p>
              <Button onClick={() => navigate("/login")} className="w-full">
                Quay lại đăng nhập
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 mb-4">
            <KeyRound className="w-10 h-10 text-primary" />
            <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
          </div>
          <p className="text-muted-foreground">Khôi phục mật khẩu tài khoản</p>
        </div>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white">
              Quên mật khẩu?
            </CardTitle>
            <CardDescription>
              Nhập email đăng ký của bạn. Chúng tôi sẽ gửi một liên kết đặt lại mật khẩu.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isGoogleUser && (
              <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-sm text-amber-600 dark:text-amber-400 flex items-start gap-2 animate-fade-in">
                <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-medium">Đăng nhập Google Sign-In</p>
                  <p className="text-xs">
                    Tài khoản này được đăng ký bằng tài khoản Google. Hãy quay lại trang
                    đăng nhập và sử dụng Google Sign-In.
                  </p>
                  <Link
                    to="/login"
                    className="text-xs font-semibold underline hover:text-amber-700 dark:hover:text-amber-300 block mt-1"
                  >
                    Quay lại Đăng nhập Google
                  </Link>
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-gray-700 dark:text-gray-300">
                  Địa chỉ Email
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

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Đang gửi yêu cầu...
                  </>
                ) : (
                  "Gửi liên kết đặt lại mật khẩu"
                )}
              </Button>
            </form>

            <div className="mt-4 text-center">
              <Link
                to="/login"
                className="inline-flex items-center text-sm text-muted-foreground hover:text-primary gap-1"
              >
                <ArrowLeft className="w-4 h-4" /> Quay lại đăng nhập
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
