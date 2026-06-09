import { useState, useEffect } from "react";
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
import { Loader2, KeyRound, CheckCircle2, XCircle, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

export function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [hasTokenError, setHasTokenError] = useState(false);

  useEffect(() => {
    if (!token) {
      setHasTokenError(true);
      toast.error("Đường dẫn đặt lại mật khẩu thiếu mã xác thực token.");
    }
  }, [token]);

  const validatePassword = (pwd: string): string | null => {
    if (pwd.length < 8) {
      return "Mật khẩu phải có ít nhất 8 ký tự";
    }
    if (!/[A-Za-z]/.test(pwd)) {
      return "Mật khẩu phải có ít nhất 1 chữ cái";
    }
    if (!/\d/.test(pwd)) {
      return "Mật khẩu phải có ít nhất 1 số";
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!token) {
      toast.error("Không tìm thấy mã xác thực token.");
      return;
    }

    if (password !== confirmPassword) {
      toast.error("Mật khẩu xác nhận không khớp.");
      return;
    }

    const passwordError = validatePassword(password);
    if (passwordError) {
      toast.error(passwordError);
      return;
    }

    setIsLoading(true);

    try {
      const response = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Đặt lại mật khẩu thất bại.");
      }

      setIsSuccess(true);
      toast.success("Đặt lại mật khẩu thành công!");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Có lỗi xảy ra, vui lòng thử lại.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  if (hasTokenError) {
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
              <div className="flex justify-center mb-4 text-red-500">
                <XCircle className="w-16 h-16" />
              </div>
              <CardTitle className="text-gray-900 dark:text-white">
                Đường dẫn không hợp lệ
              </CardTitle>
              <CardDescription>
                Mã xác thực đặt lại mật khẩu không chính xác hoặc đã bị lược bỏ.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">
                Vui lòng yêu cầu gửi lại link khôi phục mật khẩu mới.
              </p>
              <Button onClick={() => navigate("/forgot-password")} className="w-full">
                Yêu cầu liên kết mới
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

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
                Mật khẩu đã được cập nhật
              </CardTitle>
              <CardDescription>
                Bạn đã thay đổi mật khẩu thành công cho tài khoản của mình.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">
                Bây giờ bạn đã có thể đăng nhập bằng mật khẩu mới này.
              </p>
              <Button onClick={() => navigate("/login")} className="w-full">
                Đăng nhập ngay
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
          <p className="text-muted-foreground">Đặt mật khẩu mới</p>
        </div>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white">
              Tạo mật khẩu mới
            </CardTitle>
            <CardDescription>
              Hãy nhập mật khẩu mới và xác nhận để cập nhật thông tin tài khoản.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="password" className="text-gray-700 dark:text-gray-300">
                  Mật khẩu mới
                </Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="--------"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white"
                />
                <p className="text-xs text-gray-500 dark:text-muted-foreground">
                  Ít nhất 8 ký tự, bao gồm cả chữ cái và chữ số
                </p>
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="confirmPassword"
                  className="text-gray-700 dark:text-gray-300"
                >
                  Xác nhận mật khẩu mới
                </Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="--------"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white"
                />
                {password !== confirmPassword && confirmPassword && (
                  <p className="text-xs text-red-600 dark:text-red-400">
                    Mật khẩu xác nhận chưa khớp
                  </p>
                )}
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={isLoading || password !== confirmPassword}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Đang lưu mật khẩu...
                  </>
                ) : (
                  "Cập nhật mật khẩu"
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
