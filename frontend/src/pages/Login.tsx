import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { GoogleLogin, CredentialResponse } from "@react-oauth/google";
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
import { Loader2, Video, AlertCircle } from "lucide-react";
import { toast } from "sonner";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showResendBanner, setShowResendBanner] = useState(false);
  const [resendEmail, setResendEmail] = useState("");
  const [isResending, setIsResending] = useState(false);
  const { login, loginWithGoogle } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setShowResendBanner(false);

    try {
      await login(email, password);
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : "";
      if (
        errMsg.includes("chua duoc xac thuc") ||
        errMsg.includes("verification pending") ||
        errMsg.includes("chưa được xác thực")
      ) {
        setShowResendBanner(true);
        setResendEmail(email);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendVerification = async () => {
    setIsResending(true);
    try {
      const response = await fetch("/api/auth/resend-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: resendEmail }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Khong the gui lai email.");
      }

      toast.success("Da gui lai email xac thuc. Vui long kiem tra hop thu.");
      setShowResendBanner(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Co loi xay ra khi gui lai email.",
      );
    } finally {
      setIsResending(false);
    }
  };

  const handleGoogleSuccess = async (response: CredentialResponse) => {
    if (!response.credential) return;
    setIsLoading(true);
    try {
      await loginWithGoogle(response.credential);
    } catch (error) {
      // Error handled in AuthContext
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Video className="w-10 h-10 text-primary" />
            <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
          </div>
          <p className="text-muted-foreground">Đăng nhập để tiếp tục</p>
        </div>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white">Đăng nhập</CardTitle>
            <CardDescription>Nhập email và mật khẩu của bạn</CardDescription>
          </CardHeader>
          <CardContent>
            {showResendBanner && (
              <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-sm text-amber-600 dark:text-amber-400 flex items-start gap-2">
                <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-medium">Tài khoản chưa xác thực email.</p>
                  <button
                    type="button"
                    onClick={handleResendVerification}
                    disabled={isResending}
                    className="text-xs font-semibold underline hover:text-amber-700 dark:hover:text-amber-300 disabled:opacity-50 block text-left"
                  >
                    {isResending ? "Đang gửi lại..." : "Gửi lại email xác thực"}
                  </button>
                </div>
              </div>
            )}

            {/* Google Sign-In button */}
            <div className="flex justify-center mb-4">
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={() => {
                  // Silently handle - user cancelled or popup blocked
                }}
                theme="outline"
                size="large"
                text="signin_with"
                shape="rectangular"
              />
            </div>

            {/* Divider */}
            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-gray-200 dark:border-white/10" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-white dark:bg-black/40 px-2 text-muted-foreground">
                  hoặc
                </span>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-gray-700 dark:text-gray-300">
                  Email
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

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password" className="text-gray-700 dark:text-gray-300">
                    Mật khẩu
                  </Label>
                  <Link
                    to="/forgot-password"
                    className="text-xs text-primary hover:underline"
                  >
                    Quên mật khẩu?
                  </Link>
                </div>
                <Input
                  id="password"
                  type="password"
                  placeholder="--------"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white"
                />
              </div>

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Đang đăng nhập...
                  </>
                ) : (
                  "Đăng nhập"
                )}
              </Button>
            </form>

            <div className="mt-4 text-center text-sm">
              <span className="text-muted-foreground">Chưa có tài khoản? </span>
              <Link to="/register" className="text-primary hover:underline">
                Đăng ký ngay
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
