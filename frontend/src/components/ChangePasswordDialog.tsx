import React, { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Loader2, X, Lock, Eye, EyeOff, Check, AlertCircle } from "lucide-react";

interface ChangePasswordDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ChangePasswordDialog({ isOpen, onClose }: ChangePasswordDialogProps) {
  const { user, token, updateUser } = useAuth();
  const [isLoading, setIsLoading] = useState(false);

  // Form states
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Show/Hide password states
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // Password requirements checks
  const isGoogleUser = user?.auth_provider === "google";
  const isLengthValid = newPassword.length >= 8;
  const hasLetter = /[A-Za-z]/.test(newPassword);
  const hasNumber = /\d/.test(newPassword);
  const isSameAsOld = !isGoogleUser && newPassword !== "" && oldPassword === newPassword;
  const isPasswordStrong = isLengthValid && hasLetter && hasNumber && !isSameAsOld;
  const isMatch = newPassword === confirmPassword && confirmPassword !== "";

  // Reset form when modal is closed/opened
  useEffect(() => {
    if (!isOpen) {
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setShowOld(false);
      setShowNew(false);
      setShowConfirm(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!isGoogleUser && !oldPassword) {
      toast.error("Vui lòng nhập mật khẩu cũ.");
      return;
    }

    if (isSameAsOld) {
      toast.error("Mật khẩu mới phải khác mật khẩu cũ.");
      return;
    }

    if (!isPasswordStrong) {
      toast.error("Mật khẩu mới không đáp ứng đủ yêu cầu bảo mật.");
      return;
    }

    if (!isMatch) {
      toast.error("Mật khẩu xác nhận không khớp.");
      return;
    }

    setIsLoading(true);

    try {
      const response = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          old_password: isGoogleUser ? undefined : oldPassword,
          new_password: newPassword,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Có lỗi xảy ra khi thay đổi mật khẩu.");
      }

      // Update local storage user state
      if (data.user) {
        updateUser(data.user);
      }

      toast.success(data.message || "Thay đổi mật khẩu thành công!");
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Có lỗi xảy ra.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-fade-in">
      <div className="relative bg-white dark:bg-zinc-950 border border-gray-200 dark:border-white/10 rounded-2xl w-full max-w-md p-6 shadow-2xl flex flex-col gap-4 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between pb-2 border-b border-gray-100 dark:border-white/10">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-primary" />
            <h2 className="text-xl font-bold tracking-tight text-gray-900 dark:text-white">
              {isGoogleUser ? "Thiết lập mật khẩu" : "Thay đổi mật khẩu"}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors rounded-lg p-1 hover:bg-gray-100 dark:hover:bg-white/5"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Info for Google Users */}
        {isGoogleUser && (
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400 flex gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
              Tài khoản của bạn đăng nhập bằng Google và chưa có mật khẩu cục bộ. Hãy
              thiết lập mật khẩu dưới đây để có thể đăng nhập trực tiếp bằng email.
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Old Password */}
          {!isGoogleUser && (
            <div className="space-y-2">
              <Label htmlFor="old-password">Mật khẩu cũ</Label>
              <div className="relative">
                <Input
                  id="old-password"
                  type={showOld ? "text" : "password"}
                  placeholder="Nhập mật khẩu hiện tại"
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  required
                  className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowOld(!showOld)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                >
                  {showOld ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          {/* New Password */}
          <div className="space-y-2">
            <Label htmlFor="new-password">Mật khẩu mới</Label>
            <div className="relative">
              <Input
                id="new-password"
                type={showNew ? "text" : "password"}
                placeholder="Nhập mật khẩu mới"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white pr-10"
              />
              <button
                type="button"
                onClick={() => setShowNew(!showNew)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

            {isSameAsOld && (
              <div className="flex items-center gap-1.5 text-xs text-red-500 pt-0.5 animate-shake">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>Mật khẩu mới phải khác mật khẩu cũ</span>
              </div>
            )}

            {/* Password strength meter */}
            <div className="space-y-1.5 pt-1">
              <div className="text-xs text-muted-foreground">Yêu cầu mật khẩu:</div>
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1.5 text-xs">
                  {isLengthValid ? (
                    <Check className="w-3.5 h-3.5 text-green-500" />
                  ) : (
                    <div className="w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-white/15" />
                  )}
                  <span
                    className={
                      isLengthValid
                        ? "text-green-600 dark:text-green-400"
                        : "text-muted-foreground"
                    }
                  >
                    Ít nhất 8 ký tự
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  {hasLetter ? (
                    <Check className="w-3.5 h-3.5 text-green-500" />
                  ) : (
                    <div className="w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-white/15" />
                  )}
                  <span
                    className={
                      hasLetter
                        ? "text-green-600 dark:text-green-400"
                        : "text-muted-foreground"
                    }
                  >
                    Chứa ít nhất 1 chữ cái (a-z, A-Z)
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  {hasNumber ? (
                    <Check className="w-3.5 h-3.5 text-green-500" />
                  ) : (
                    <div className="w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-white/15" />
                  )}
                  <span
                    className={
                      hasNumber
                        ? "text-green-600 dark:text-green-400"
                        : "text-muted-foreground"
                    }
                  >
                    Chứa ít nhất 1 chữ số (0-9)
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Confirm Password */}
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Xác nhận mật khẩu mới</Label>
            <div className="relative">
              <Input
                id="confirm-password"
                type={showConfirm ? "text" : "password"}
                placeholder="Nhập lại mật khẩu mới"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="bg-white border-gray-200 text-gray-900 dark:bg-white/5 dark:border-white/10 dark:text-white pr-10"
              />
              <button
                type="button"
                onClick={() => setShowConfirm(!showConfirm)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                {showConfirm ? (
                  <EyeOff className="w-4 h-4" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
              </button>
            </div>
            {confirmPassword && (
              <div className="flex items-center gap-1.5 text-xs pt-0.5">
                {isMatch ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-green-500" />
                    <span className="text-green-600 dark:text-green-400">
                      Mật khẩu xác nhận đã khớp
                    </span>
                  </>
                ) : (
                  <>
                    <X className="w-3.5 h-3.5 text-red-500" />
                    <span className="text-red-500">Mật khẩu xác nhận chưa khớp</span>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 pt-2 justify-end">
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              disabled={isLoading}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              Hủy
            </Button>
            <Button
              type="submit"
              disabled={isLoading || !isPasswordStrong || !isMatch}
              className="px-5"
            >
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang xử lý...
                </>
              ) : isGoogleUser ? (
                "Thiết lập"
              ) : (
                "Cập nhật"
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
