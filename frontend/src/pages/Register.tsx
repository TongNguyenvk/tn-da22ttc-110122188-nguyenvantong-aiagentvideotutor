import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { Loader2, Video, Mail } from "lucide-react";
import { toast } from "sonner";

export function Register() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const { register, loginWithGoogle } = useAuth();
  const navigate = useNavigate();

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

    if (password !== confirmPassword) {
      toast.error("Mật khẩu không khớp");
      return;
    }

    // Validate password strength
    const passwordError = validatePassword(password);
    if (passwordError) {
      toast.error(passwordError);
      return;
    }

    setIsLoading(true);

    try {
      await register(email, password, name);
      setIsSuccess(true);
    } catch (error) {
      // Error handled in AuthContext
    } finally {
      setIsLoading(false);
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

  if (isSuccess) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <div className="flex items-center justify-center gap-2 mb-4">
              <Video className="w-10 h-10 text-primary" />
              <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
            </div>
          </div>

          <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
            <CardHeader className="text-center">
              <div className="flex justify-center mb-4 text-primary">
                <Mail className="w-16 h-16 animate-bounce" />
              </div>
              <CardTitle className="text-gray-900 dark:text-white">
                Kiểm tra email của bạn
              </CardTitle>
              <CardDescription>
                Chúng tôi đã gửi một liên kết xác thực tài khoản đến email{" "}
                <strong>{email}</strong>.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">
                Vui lòng kiểm tra hộp thư (và cả hộp thư rác/spam) và nhấp vào liên kết để
                kích hoạt tài khoản.
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
            <Video className="w-10 h-10 text-primary" />
            <h1 className="text-4xl font-bold tracking-tight">WebReel</h1>
          </div>
          <p className="text-muted-foreground">Tạo tài khoản mới</p>
        </div>

        <Card className="border border-gray-200 shadow-lg bg-white dark:border-white/10 dark:bg-black/40 dark:backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white">Đăng ký</CardTitle>
            <CardDescription>Điền thông tin để tạo tài khoản</CardDescription>
          </CardHeader>
          <CardContent>
            {/* Google Sign-In button */}
            <div className="flex justify-center mb-4">
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={() => {
                  // Silently handle - user cancelled or popup blocked
                }}
                theme="outline"
                size="large"
                text="signup_with"
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
                <Label htmlFor="name" className="text-gray-700 dark:text-gray-300">
                  Họ và tên
                </Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="Nguyen Van A"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white"
                />
              </div>

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
                <Label htmlFor="password" className="text-gray-700 dark:text-gray-300">
                  Mật khẩu
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
                  Ít nhất 8 ký tự, có chữ cái và số
                </p>
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="confirmPassword"
                  className="text-gray-700 dark:text-gray-300"
                >
                  Xác nhận mật khẩu
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
                    Mật khẩu không khớp
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
                    Đang đăng ký...
                  </>
                ) : (
                  "Đăng ký"
                )}
              </Button>
            </form>

            <div className="mt-4 text-center text-sm">
              <span className="text-muted-foreground">Đã có tài khoản? </span>
              <Link to="/login" className="text-primary hover:underline">
                Đăng nhập
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
