import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

interface User {
  user_id: string;
  email: string;
  name: string;
  auth_provider: "local" | "google" | "both";
  avatar_url?: string | null;
  role: "user" | "admin";
  tier: string;
  status: string;
  email_verified: boolean;
  quota: {
    videos_per_month: number;
    videos_used_this_month: number;
  };
  created_at: string;
  last_login?: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  loginWithGoogle: (credential: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    name: string,
  ) => Promise<{ message: string; email: string }>;
  logout: () => void;
  updateUser: (user: User) => void;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const API_BASE = "";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser = localStorage.getItem("user");

    if (storedToken && storedUser) {
      setToken(storedToken);
      setUser(JSON.parse(storedUser));
    }

    setIsLoading(false);
  }, []);

  const _handleAuthSuccess = (data: { access_token: string; user: User }) => {
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem("token", data.access_token);
    localStorage.setItem("user", JSON.stringify(data.user));

    if (data.user.role === "admin") {
      navigate("/admin");
    } else {
      navigate("/");
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Login failed");
      }

      const data = await response.json();
      _handleAuthSuccess(data);
      toast.success("Đăng nhập thành công!");
    } catch (error) {
      toast.error("Đăng nhập thất bại", {
        description:
          error instanceof Error ? error.message : "Vui lòng kiểm tra lại thông tin",
      });
      throw error;
    }
  };

  const loginWithGoogle = async (credential: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Google login failed");
      }

      const data = await response.json();
      _handleAuthSuccess(data);
      toast.success("Đăng nhập bằng Google thành công!");
    } catch (error) {
      toast.error("Đăng nhập Google thất bại", {
        description: error instanceof Error ? error.message : "Vui lòng thử lại",
      });
      throw error;
    }
  };

  const register = async (email: string, password: string, name: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, name }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Registration failed");
      }

      const data = await response.json();
      toast.success("Dang ky thanh cong! Vui long kiem tra email.");
      return data;
    } catch (error) {
      toast.error("Dang ky that bai", {
        description: error instanceof Error ? error.message : "Vui long thu lai",
      });
      throw error;
    }
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    toast.info("Đã đăng xuất");
    navigate("/login");
  };

  const updateUser = (newUser: User) => {
    setUser(newUser);
    localStorage.setItem("user", JSON.stringify(newUser));
  };

  const value = {
    user,
    token,
    login,
    loginWithGoogle,
    register,
    logout,
    updateUser,
    isLoading,
    isAuthenticated: !!token && !!user,
    isAdmin: user?.role === "admin",
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
