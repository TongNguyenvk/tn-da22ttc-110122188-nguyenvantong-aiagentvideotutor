import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GoogleOAuthProvider } from "@react-oauth/google";
import {
  BrowserRouter,
  Routes,
  Route,
  Link,
  useLocation,
  Navigate,
} from "react-router-dom";
import {
  LayoutDashboard,
  Video,
  LogOut,
  User,
  Users,
  Snowflake,
  Key,
  Bot,
} from "lucide-react";
import { ThemeProvider } from "next-themes";
import { Dashboard } from "@/pages/Dashboard";
import { Create } from "@/pages/Create";
import { Admin } from "@/pages/Admin";
import { AdminSessionManager } from "@/pages/AdminSessionManager";
import { AdminAgentConfig } from "@/pages/AdminAgentConfig";
import { Login } from "@/pages/Login";
import { Register } from "@/pages/Register";
import { VerifyEmail } from "@/pages/VerifyEmail";
import { ForgotPassword } from "@/pages/ForgotPassword";
import { ResetPassword } from "@/pages/ResetPassword";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ChangePasswordDialog } from "@/components/ChangePasswordDialog";

const queryClient = new QueryClient();

function Sidebar() {
  const location = useLocation();
  const { user, logout, isAdmin } = useAuth();
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);

  // Admin có menu riêng, không có Create
  const navItems = isAdmin
    ? [
        { name: "Tổng quan", path: "/admin", icon: LayoutDashboard, show: true },
        { name: "Người dùng", path: "/admin/users", icon: Users, show: true },
        { name: "Công việc", path: "/admin/jobs", icon: Video, show: true },
        { name: "Session Manager", path: "/admin/session", icon: Snowflake, show: true },
        { name: "Cấu hình Agent", path: "/admin/agent-config", icon: Bot, show: true },
      ]
    : [
        { name: "Tổng quan", path: "/", icon: LayoutDashboard, show: true },
        { name: "Tạo mới", path: "/create", icon: Video, show: true },
      ];

  return (
    <aside className="w-64 bg-background border-r p-6 flex flex-col gap-6 h-full">
      <div className="font-bold text-2xl tracking-tight">WebReel</div>

      <div className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-white/10">
        <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
          <User className="w-5 h-5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{user?.name}</div>
          <div className="text-xs text-muted-foreground truncate">{user?.email}</div>
        </div>
      </div>

      <nav className="flex flex-col gap-2 flex-1">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-4 py-2 rounded-md text-sm font-medium transition-colors ${isActive ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            >
              <item.icon className="w-4 h-4" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-white/10 pt-4 space-y-2">
        <div className="flex items-center justify-between px-2">
          <span className="text-sm text-muted-foreground">Giao diện</span>
          <ThemeToggle />
        </div>
        <Button
          variant="outline"
          className="w-full justify-start border-white/10 hover:bg-primary/10 hover:text-primary hover:border-primary/20"
          onClick={() => setIsChangePasswordOpen(true)}
        >
          <Key className="w-4 h-4 mr-2" />
          Đổi mật khẩu
        </Button>
        <Button
          variant="outline"
          className="w-full justify-start border-white/10 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/20"
          onClick={logout}
        >
          <LogOut className="w-4 h-4 mr-2" />
          Đăng xuất
        </Button>
      </div>

      <ChangePasswordDialog
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
      />
    </aside>
  );
}

function AppLayout() {
  const { isAdmin } = useAuth();

  // Admin có layout riêng
  if (isAdmin) {
    return (
      <div className="min-h-screen bg-background flex text-foreground">
        <Sidebar />
        <main className="flex-1 p-8">
          <Routes>
            <Route path="/admin" element={<Admin />} />
            <Route path="/admin/users" element={<Admin />} />
            <Route path="/admin/jobs" element={<Admin />} />
            <Route path="/admin/session" element={<AdminSessionManager />} />
            <Route path="/admin/agent-config" element={<AdminAgentConfig />} />
            <Route path="*" element={<Navigate to="/admin" replace />} />
          </Routes>
        </main>
      </div>
    );
  }

  // User có layout bình thường
  return (
    <div className="min-h-screen bg-background flex text-foreground">
      <Sidebar />
      <main className="flex-1 p-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/create" element={<Create />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
      <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <AuthProvider>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/verify-email" element={<VerifyEmail />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route
                  path="/*"
                  element={
                    <ProtectedRoute>
                      <AppLayout />
                    </ProtectedRoute>
                  }
                />
              </Routes>
              <Toaster />
            </AuthProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </GoogleOAuthProvider>
    </ThemeProvider>
  );
}

export default App;
