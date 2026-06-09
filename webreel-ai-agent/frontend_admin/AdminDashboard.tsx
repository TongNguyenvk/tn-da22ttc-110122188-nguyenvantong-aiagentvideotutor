/**
 * Admin Dashboard - Cookie Management & System Monitoring
 *
 * Features:
 * - Cookie expiry status with color-coded badges
 * - Embedded noVNC for manual login
 * - Auto-refresh status every 5 minutes
 * - Notification when cookies need refresh
 */

import React, { useState, useEffect } from "react";

interface CookieStatus {
  status: "ok" | "warning" | "critical" | "expired" | "unknown";
  days_left: number | null;
  expires_at: string | null;
  message: string;
  needs_login: boolean;
  cookie_count?: number;
}

export default function AdminDashboard() {
  const [cookieStatus, setCookieStatus] = useState<CookieStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNoVNC, setShowNoVNC] = useState(false);
  const [novncUrl, setNovncUrl] = useState("");
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  // Fetch cookie status
  const fetchCookieStatus = async () => {
    try {
      const response = await fetch("/admin/cookie-status");
      const data = await response.json();
      setCookieStatus(data);
      setLastChecked(new Date());

      // Show notification if critical
      if (data.status === "critical" || data.status === "expired") {
        showNotification(data.message);
      }
    } catch (error) {
      console.error("Failed to fetch cookie status:", error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch noVNC URL
  const fetchNoVNCUrl = async () => {
    try {
      const response = await fetch("/admin/novnc-url");
      const data = await response.json();
      setNovncUrl(data.url);
    } catch (error) {
      console.error("Failed to fetch noVNC URL:", error);
    }
  };

  // Verify cookies after login
  const verifyCookies = async () => {
    try {
      const response = await fetch("/admin/verify-cookies", { method: "POST" });
      const data = await response.json();

      if (data.success) {
        alert("✅ Login successful! Cookies verified.");
        setShowNoVNC(false);
        fetchCookieStatus(); // Refresh status
      } else {
        alert("❌ " + data.message);
      }
    } catch (error) {
      alert("Error verifying cookies: " + error);
    }
  };

  // Show browser notification
  const showNotification = (message: string) => {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("WebReel Admin Alert", {
        body: message,
        icon: "/favicon.ico",
        tag: "cookie-alert",
      });
    }
  };

  // Request notification permission
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // Auto-refresh every 5 minutes
  useEffect(() => {
    fetchCookieStatus();
    fetchNoVNCUrl();

    const interval = setInterval(fetchCookieStatus, 5 * 60 * 1000); // 5 minutes
    return () => clearInterval(interval);
  }, []);

  // Status badge color
  const getStatusColor = (status: string) => {
    switch (status) {
      case "ok":
        return "bg-green-500";
      case "warning":
        return "bg-yellow-500";
      case "critical":
        return "bg-red-500";
      case "expired":
        return "bg-red-700";
      default:
        return "bg-gray-500";
    }
  };

  // Status icon
  const getStatusIcon = (status: string) => {
    switch (status) {
      case "ok":
        return "✅";
      case "warning":
        return "⚠️";
      case "critical":
        return "🚨";
      case "expired":
        return "❌";
      default:
        return "❓";
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">WebReel Admin Dashboard</h1>

        {/* Cookie Status Card */}
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">OneDrive Cookie Status</h2>
            <button
              onClick={fetchCookieStatus}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              🔄 Refresh
            </button>
          </div>

          {cookieStatus && (
            <div className="space-y-4">
              {/* Status Badge */}
              <div className="flex items-center space-x-4">
                <span className="text-4xl">{getStatusIcon(cookieStatus.status)}</span>
                <div>
                  <div className="flex items-center space-x-2">
                    <span
                      className={`px-3 py-1 rounded-full text-white text-sm font-semibold ${getStatusColor(cookieStatus.status)}`}
                    >
                      {cookieStatus.status.toUpperCase()}
                    </span>
                    {cookieStatus.days_left !== null && (
                      <span className="text-2xl font-bold">
                        {cookieStatus.days_left} days left
                      </span>
                    )}
                  </div>
                  <p className="text-gray-600 mt-1">{cookieStatus.message}</p>
                </div>
              </div>

              {/* Details */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Expires at:</span>
                  <span className="ml-2 font-mono">
                    {cookieStatus.expires_at
                      ? new Date(cookieStatus.expires_at).toLocaleString()
                      : "Unknown"}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Cookie count:</span>
                  <span className="ml-2 font-mono">{cookieStatus.cookie_count || 0}</span>
                </div>
                <div>
                  <span className="text-gray-500">Last checked:</span>
                  <span className="ml-2 font-mono">
                    {lastChecked?.toLocaleTimeString()}
                  </span>
                </div>
              </div>

              {/* Login Button */}
              {cookieStatus.needs_login && (
                <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded">
                  <p className="text-red-700 font-semibold mb-2">
                    🚨 Action Required: Manual Login Needed
                  </p>
                  <button
                    onClick={() => setShowNoVNC(!showNoVNC)}
                    className="px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 font-semibold"
                  >
                    {showNoVNC ? "❌ Close Login Window" : "🔐 Login to OneDrive"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Embedded noVNC */}
        {showNoVNC && (
          <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">OneDrive Login (noVNC)</h2>
              <button
                onClick={verifyCookies}
                className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
              >
                ✅ Verify Login
              </button>
            </div>

            {/* Instructions */}
            <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded">
              <p className="font-semibold mb-2">📝 Instructions:</p>
              <ol className="list-decimal list-inside space-y-1 text-sm">
                <li>
                  In the browser below, navigate to{" "}
                  <code className="bg-gray-200 px-1">https://onedrive.live.com</code>
                </li>
                <li>Login with your Microsoft account</li>
                <li>
                  <strong>IMPORTANT:</strong> Tick "Keep me signed in" checkbox
                </li>
                <li>After login, click "Verify Login" button above</li>
              </ol>
            </div>

            {/* noVNC iframe */}
            <div className="border-4 border-gray-300 rounded-lg overflow-hidden">
              <iframe
                src={novncUrl}
                className="w-full h-[600px]"
                title="noVNC Remote Desktop"
              />
            </div>

            <p className="text-sm text-gray-500 mt-2">
              noVNC is served through the Nginx reverse proxy at /novnc/. No SSH tunnel
              required.
            </p>
          </div>
        )}

        {/* System Info */}
        <div className="bg-white rounded-lg shadow-lg p-6">
          <h2 className="text-xl font-semibold mb-4">System Information</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Auto-refresh interval:</span>
              <span className="font-mono">5 minutes</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Cookie refresh threshold:</span>
              <span className="font-mono">7 days</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Recommended login frequency:</span>
              <span className="font-mono">Every 60-80 days</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
