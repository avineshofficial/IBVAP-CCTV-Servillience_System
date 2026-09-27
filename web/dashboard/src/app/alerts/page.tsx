"use client";
import { useEffect, useState } from "react";
import { getAlerts, updateAlert, connectAlertWebSocket } from "@/lib/api";
import type { Alert } from "@/lib/api";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState({ status: "", severity: "" });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAlerts();
    const interval = setInterval(loadAlerts, 3000);
    const ws = connectAlertWebSocket((data) => {
      if (data.type === "new_alerts" || data.type === "alert_updated") {
        loadAlerts();
      }
    });

    return () => {
      clearInterval(interval);
      ws?.close();
    };
  }, [filter]);

  async function loadAlerts() {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: "100" };
      if (filter.status) params.status = filter.status;
      if (filter.severity) params.severity = filter.severity;
      const data = await getAlerts(params);
      setAlerts(data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }

  async function handleAction(id: number, status: string) {
    try {
      await updateAlert(id, { status });
      loadAlerts();
    } catch (e) { console.error(e); }
  }

  const sevColors: Record<string, string> = {
    critical: "badge-critical", high: "badge-high", medium: "badge-medium", low: "badge-low",
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">🚨 Alert Management</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            {alerts.length} alerts · Filter, acknowledge, resolve, or mark as false positive
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadAlerts}>↻ Refresh</button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-6">
        {["", "new", "acknowledged", "resolved", "false_positive"].map((s) => (
          <button
            key={s}
            className={`btn ${filter.status === s ? "btn-primary" : "btn-outline"}`}
            onClick={() => setFilter({ ...filter, status: s })}
          >
            {s || "All"}
          </button>
        ))}
        <div className="mx-2" style={{ borderLeft: "1px solid var(--border-subtle)" }} />
        {["", "critical", "high", "medium", "low"].map((s) => (
          <button
            key={s}
            className={`btn ${filter.severity === s ? "btn-primary" : "btn-outline"}`}
            onClick={() => setFilter({ ...filter, severity: s })}
          >
            {s || "Any Severity"}
          </button>
        ))}
      </div>

      {/* Alert Table */}
      <div className="glass-card overflow-hidden">
        {loading ? (
          <div className="p-12 text-center" style={{ color: "var(--text-secondary)" }}>Loading...</div>
        ) : alerts.length === 0 ? (
          <div className="p-12 text-center" style={{ color: "var(--text-secondary)" }}>
            <p className="text-4xl mb-3">🛡️</p>
            <p className="text-lg">No alerts found</p>
            <p className="text-sm mt-1">Run the edge pipeline to generate detection events and alerts</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Severity</th>
                <th>Type</th>
                <th>Message</th>
                <th>Status</th>
                <th>Time</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr key={alert.id}>
                  <td className="font-mono text-xs">#{alert.id}</td>
                  <td>
                    <span className={`badge ${sevColors[alert.severity] || "badge-medium"}`}>
                      {alert.severity}
                    </span>
                  </td>
                  <td className="text-sm">{alert.alert_type}</td>
                  <td className="text-sm max-w-xs truncate">{alert.message || "—"}</td>
                  <td>
                    <span
                      className="text-xs px-2 py-1 rounded font-medium"
                      style={{
                        background: alert.status === "new" ? "rgba(59,130,246,0.15)" :
                          alert.status === "resolved" ? "rgba(16,185,129,0.15)" :
                          alert.status === "false_positive" ? "rgba(245,158,11,0.15)" :
                          "rgba(139,92,246,0.15)",
                        color: alert.status === "new" ? "var(--accent-blue)" :
                          alert.status === "resolved" ? "var(--accent-green)" :
                          alert.status === "false_positive" ? "var(--accent-amber)" :
                          "var(--accent-purple)",
                      }}
                    >
                      {alert.status}
                    </span>
                  </td>
                  <td className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {alert.created_at ? new Date(alert.created_at).toLocaleString() : "—"}
                  </td>
                  <td>
                    <div className="flex gap-1">
                      {alert.status === "new" && (
                        <button className="btn btn-outline text-xs py-1 px-2"
                          onClick={() => handleAction(alert.id, "acknowledged")}>
                          ✓ Ack
                        </button>
                      )}
                      {alert.status !== "resolved" && (
                        <button className="btn btn-success text-xs py-1 px-2"
                          onClick={() => handleAction(alert.id, "resolved")}>
                          ✓ Resolve
                        </button>
                      )}
                      {alert.status === "new" && (
                        <button className="btn btn-outline text-xs py-1 px-2"
                          onClick={() => handleAction(alert.id, "false_positive")}>
                          ✗ FP
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
