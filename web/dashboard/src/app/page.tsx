"use client";
import { useEffect, useState } from "react";
import { getStats, getAlerts, getCameras, connectAlertWebSocket } from "@/lib/api";
import type { DashboardStats, Alert, Camera } from "@/lib/api";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);

    const ws = connectAlertWebSocket((data) => {
      setWsConnected(true);
      if (data.type === "new_alerts" || data.type === "alert_updated") {
        loadData();
      }
    });

    return () => {
      clearInterval(interval);
      ws?.close();
    };
  }, []);

  async function loadData() {
    try {
      const [s, a, c] = await Promise.all([getStats(), getAlerts({ limit: "10" }), getCameras()]);
      setStats(s);
      setAlerts(a);
      setCameras(c);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error("Failed to load data:", e);
    }
  }

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
            Command Dashboard
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Real-time border surveillance overview
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className={`status-dot ${wsConnected ? "status-online" : "status-offline"}`}></span>
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {wsConnected ? "Live" : "Connecting..."}
            </span>
          </div>
          <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Updated: {lastUpdate}
          </span>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          title="Cameras Online"
          value={`${stats?.cameras_online ?? 0}/${stats?.total_cameras ?? 0}`}
          icon="📹" color="var(--accent-cyan)"
        />
        <StatCard
          title="Active Alerts"
          value={stats?.active_alerts ?? 0}
          icon="🚨" color="var(--accent-red)"
          highlight={!!stats && stats.critical_alerts > 0}
        />
        <StatCard
          title="Total Events"
          value={stats?.total_events ?? 0}
          icon="📡" color="var(--accent-blue)"
        />
        <StatCard
          title="System Uptime"
          value={stats ? formatUptime(stats.system_uptime) : "—"}
          icon="⏱️" color="var(--accent-green)"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Alerts */}
        <div className="lg:col-span-2 glass-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Recent Alerts</h2>
            <a href="/alerts" className="text-sm" style={{ color: "var(--accent-blue)" }}>
              View All →
            </a>
          </div>
          <div className="space-y-3">
            {alerts.length === 0 ? (
              <div className="text-center py-8" style={{ color: "var(--text-secondary)" }}>
                <p className="text-4xl mb-2">🛡️</p>
                <p>No alerts — system is clear</p>
                <p className="text-xs mt-1">Run the edge pipeline to generate detection events</p>
              </div>
            ) : (
              alerts.slice(0, 6).map((alert) => (
                <AlertRow key={alert.id} alert={alert} />
              ))
            )}
          </div>
        </div>

        {/* Camera Status */}
        <div className="glass-card p-5">
          <h2 className="text-lg font-semibold mb-4">Camera Status</h2>
          <div className="space-y-3">
            {cameras.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No cameras registered. Start the core backend to seed demo data.
              </p>
            ) : (
              cameras.map((cam) => (
                <div
                  key={cam.id}
                  className="flex items-center justify-between p-3 rounded-lg"
                  style={{ background: "var(--bg-secondary)" }}
                >
                  <div className="flex items-center gap-3">
                    <span className={`status-dot ${cam.status === "online" ? "status-online" : "status-offline"}`}></span>
                    <div>
                      <p className="text-sm font-medium">{cam.name}</p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        {cam.camera_uid} · {cam.bop_id}
                      </p>
                    </div>
                  </div>
                  <span
                    className="text-xs px-2 py-1 rounded"
                    style={{
                      background: cam.status === "online" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                      color: cam.status === "online" ? "var(--accent-green)" : "var(--accent-red)",
                    }}
                  >
                    {cam.status}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Capabilities Section */}
      <div className="mt-8 glass-card p-5">
        <h2 className="text-lg font-semibold mb-4">🎯 Active Capabilities</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { name: "Human Detection", icon: "🚶", status: "active" },
            { name: "Vehicle Detection", icon: "🚗", status: "active" },
            { name: "Face Recognition", icon: "👤", status: "active" },
            { name: "ANPR", icon: "🔢", status: "active" },
            { name: "Virtual Fence", icon: "🔒", status: "active" },
            { name: "Activity Detection", icon: "⚡", status: "active" },
            { name: "Night Enhancement", icon: "🌙", status: "active" },
            { name: "Audit Chain", icon: "🔗", status: "active" },
          ].map((cap) => (
            <div
              key={cap.name}
              className="flex items-center gap-3 p-3 rounded-lg"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)" }}
            >
              <span className="text-xl">{cap.icon}</span>
              <div>
                <p className="text-xs font-medium">{cap.name}</p>
                <p className="text-xs" style={{ color: "var(--accent-green)" }}>● Active</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ title, value, icon, color, highlight }: {
  title: string; value: string | number; icon: string; color: string; highlight?: boolean;
}) {
  return (
    <div
      className="stat-card"
      style={highlight ? { borderColor: "var(--accent-red)", boxShadow: "0 0 15px var(--glow-red)" } : {}}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-2xl">{icon}</span>
        {highlight && <span className="badge badge-critical animate-pulse-glow">!</span>}
      </div>
      <p className="text-2xl font-bold" style={{ color }}>{value}</p>
      <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{title}</p>
    </div>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const severityColors: Record<string, string> = {
    critical: "badge-critical", high: "badge-high", medium: "badge-medium", low: "badge-low",
  };
  const time = alert.created_at ? new Date(alert.created_at).toLocaleTimeString() : "—";

  return (
    <div
      className="flex items-center justify-between p-3 rounded-lg"
      style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)" }}
    >
      <div className="flex items-center gap-3">
        <span className={`badge ${severityColors[alert.severity] || "badge-medium"}`}>
          {alert.severity}
        </span>
        <div>
          <p className="text-sm font-medium">{alert.message || alert.alert_type}</p>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {alert.alert_type} · {time}
          </p>
        </div>
      </div>
      <span
        className="text-xs px-2 py-1 rounded"
        style={{
          background: alert.status === "new" ? "rgba(59,130,246,0.15)" : "rgba(16,185,129,0.15)",
          color: alert.status === "new" ? "var(--accent-blue)" : "var(--accent-green)",
        }}
      >
        {alert.status}
      </span>
    </div>
  );
}
