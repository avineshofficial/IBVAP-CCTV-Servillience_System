"use client";
import { useEffect, useState } from "react";
import { getStats, getAlerts, getEvents, getAuditStats } from "@/lib/api";
import type { DashboardStats, Alert, DetectionEvent, AuditStats } from "@/lib/api";

export default function AnalyticsPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [auditStats, setAuditStats] = useState<AuditStats | null>(null);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [s, a, e, as_] = await Promise.all([
        getStats(), getAlerts({ limit: "200" }), getEvents({ limit: "200" }), getAuditStats(),
      ]);
      setStats(s);
      setAlerts(a);
      setEvents(e);
      setAuditStats(as_);
    } catch (e) { console.error(e); }
  }

  // Compute analytics
  const alertsByType = alerts.reduce((acc, a) => {
    acc[a.alert_type] = (acc[a.alert_type] || 0) + 1; return acc;
  }, {} as Record<string, number>);

  const alertsBySeverity = alerts.reduce((acc, a) => {
    acc[a.severity] = (acc[a.severity] || 0) + 1; return acc;
  }, {} as Record<string, number>);

  const alertsByStatus = alerts.reduce((acc, a) => {
    acc[a.status] = (acc[a.status] || 0) + 1; return acc;
  }, {} as Record<string, number>);

  const eventsByType = events.reduce((acc, e) => {
    acc[e.event_type] = (acc[e.event_type] || 0) + 1; return acc;
  }, {} as Record<string, number>);

  const falsePositives = alertsByStatus["false_positive"] || 0;
  const totalAlerts = alerts.length;
  const fpRate = totalAlerts > 0 ? ((falsePositives / totalAlerts) * 100).toFixed(1) : "0.0";

  const formatUptime = (s: number) => {
    const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m ${Math.floor(s % 60)}s`;
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold">📈 Analytics & Metrics</h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          System performance, detection statistics, and false positive tracking
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <KPICard title="System Uptime" value={stats ? formatUptime(stats.system_uptime) : "—"} color="var(--accent-green)" />
        <KPICard title="Total Events" value={stats?.total_events ?? 0} color="var(--accent-blue)" />
        <KPICard title="Total Alerts" value={stats?.total_alerts ?? 0} color="var(--accent-amber)" />
        <KPICard title="False Positive Rate" value={`${fpRate}%`} color={Number(fpRate) < 10 ? "var(--accent-green)" : "var(--accent-red)"} />
        <KPICard title="Audit Records" value={auditStats?.total_records ?? 0} color="var(--accent-purple)" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Alerts by Severity */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold mb-4">Alerts by Severity</h3>
          <div className="space-y-3">
            {["critical", "high", "medium", "low"].map((sev) => {
              const count = alertsBySeverity[sev] || 0;
              const pct = totalAlerts > 0 ? (count / totalAlerts) * 100 : 0;
              const colors: Record<string, string> = {
                critical: "var(--accent-red)", high: "var(--accent-amber)",
                medium: "var(--accent-blue)", low: "var(--accent-green)",
              };
              return (
                <div key={sev}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="capitalize">{sev}</span>
                    <span>{count} ({pct.toFixed(0)}%)</span>
                  </div>
                  <div className="h-2 rounded-full" style={{ background: "var(--bg-secondary)" }}>
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: colors[sev], minWidth: count > 0 ? "4px" : "0" }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Alerts by Status */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold mb-4">Alerts by Status</h3>
          <div className="space-y-3">
            {["new", "acknowledged", "resolved", "false_positive"].map((status) => {
              const count = alertsByStatus[status] || 0;
              const pct = totalAlerts > 0 ? (count / totalAlerts) * 100 : 0;
              const colors: Record<string, string> = {
                new: "var(--accent-blue)", acknowledged: "var(--accent-purple)",
                resolved: "var(--accent-green)", false_positive: "var(--accent-amber)",
              };
              return (
                <div key={status}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="capitalize">{status.replace("_", " ")}</span>
                    <span>{count} ({pct.toFixed(0)}%)</span>
                  </div>
                  <div className="h-2 rounded-full" style={{ background: "var(--bg-secondary)" }}>
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: colors[status], minWidth: count > 0 ? "4px" : "0" }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Events by Type */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold mb-4">Detections by Type</h3>
          {Object.keys(eventsByType).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No events recorded yet</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(eventsByType)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between p-2 rounded"
                    style={{ background: "var(--bg-secondary)" }}>
                    <span className="text-sm capitalize">{type.replace("_", " ")}</span>
                    <span className="font-mono text-sm font-bold" style={{ color: "var(--accent-cyan)" }}>{count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>

        {/* Alert Types */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold mb-4">Alert Types</h3>
          {Object.keys(alertsByType).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No alerts recorded yet</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(alertsByType)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between p-2 rounded"
                    style={{ background: "var(--bg-secondary)" }}>
                    <span className="text-sm capitalize">{type.replace("_", " ")}</span>
                    <span className="font-mono text-sm font-bold" style={{ color: "var(--accent-amber)" }}>{count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function KPICard({ title, value, color }: { title: string; value: string | number; color: string }) {
  return (
    <div className="stat-card">
      <p className="text-xl font-bold" style={{ color }}>{value}</p>
      <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{title}</p>
    </div>
  );
}
