"use client";
import React, { useEffect, useState, useCallback } from "react";
import {
  getAlerts,
  updateAlert,
  purgeAlerts,
  deleteAlert,
  connectAlertWebSocket,
  getMediaUrl,
} from "@/lib/api";
import type { Alert } from "@/lib/api";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState({ status: "", severity: "" });
  const [loading, setLoading] = useState(true);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [videoRetryKey, setVideoRetryKey] = useState(0);
  const [videoBuffering, setVideoBuffering] = useState(false);

  const openAlertModal = (alert: Alert) => {
    setSelectedAlert(alert);
    setVideoRetryKey(0);
    setVideoBuffering(false);
  };

  const loadAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: "100" };
      if (filter.status) params.status = filter.status;
      if (filter.severity) params.severity = filter.severity;
      const data = await getAlerts(params);
      setAlerts(Array.isArray(data) ? data : []);
    } catch {
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [filter.status, filter.severity]);

  useEffect(() => {
    let isSubscribed = true;

    async function fetchInitial() {
      try {
        const params: Record<string, string> = { limit: "100" };
        if (filter.status) params.status = filter.status;
        if (filter.severity) params.severity = filter.severity;
        const data = await getAlerts(params);
        if (isSubscribed) {
          setAlerts(Array.isArray(data) ? data : []);
          setLoading(false);
        }
      } catch {
        if (isSubscribed) {
          setAlerts([]);
          setLoading(false);
        }
      }
    }

    fetchInitial();
    const interval = setInterval(() => {
      loadAlerts();
    }, 3000);

    const ws = connectAlertWebSocket((data) => {
      if (data.type === "new_alerts" || data.type === "alert_updated") {
        loadAlerts();
      }
    });

    return () => {
      isSubscribed = false;
      clearInterval(interval);
      ws?.close();
    };
  }, [filter, loadAlerts]);

  async function handleAction(id: number, status: "acknowledged" | "resolved" | "false_positive") {
    try {
      await updateAlert(id, { status });
      if (selectedAlert && selectedAlert.id === id) {
        setSelectedAlert((prev) => (prev ? { ...prev, status } : null));
      }
      loadAlerts();
    } catch (e) {
      console.error(e);
    }
  }

  async function handlePurgeAll() {
    if (confirm("Are you sure you want to clear and purge all unwanted alerts from the queue?")) {
      try {
        await purgeAlerts();
        setSelectedAlert(null);
        await loadAlerts();
      } catch (e) {
        console.error(e);
      }
    }
  }

  async function handleDeleteSingle(id: number) {
    try {
      await deleteAlert(id);
      if (selectedAlert?.id === id) setSelectedAlert(null);
      await loadAlerts();
    } catch (e) {
      console.error(e);
    }
  }

  const sevBadges: Record<string, string> = {
    critical: "badge-critical",
    high: "badge-high",
    medium: "badge-medium",
    low: "badge-low",
  };

  const getClipUrl = (alert: Alert): string | null => {
    if (!alert.data_json) return null;
    const clip = alert.data_json["clip_url"] as string | undefined;
    return clip && clip.length > 0 ? clip : null;
  };

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      {/* Tactical Incident Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#162035] pb-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_6px_#f43f5e] animate-pulse"></span>
            <h1 className="text-sm font-bold uppercase tracking-widest text-slate-100 font-mono">
              INCIDENT DISPATCH & EVIDENCE LEDGER
            </h1>
            <span className="badge-status badge-critical">
              REAL-TIME DISPATCH
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-mono mt-0.5">
            Real-time border intrusion monitoring · Incident video clip replay · Post Commander verification
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handlePurgeAll}
            className="btn-tactical-outline text-[11px] font-mono uppercase tracking-wider text-rose-400 hover:text-rose-200 border-rose-900/60 hover:border-rose-700 bg-rose-950/20 py-1 px-2.5"
          >
            🗑 Clear Alert Queue
          </button>
          <button
            onClick={loadAlerts}
            className="btn-tactical-outline text-[11px] font-mono uppercase tracking-wider py-1 px-2.5"
          >
            ↻ Refresh Incidents
          </button>
        </div>
      </div>

      {/* High-Precision Filter Toolbar */}
      <div className="flex flex-wrap items-center gap-2.5 bg-[#090e1b] p-2.5 rounded-[4px] border border-[#162035] text-[11px] font-mono">
        <span className="text-slate-400 uppercase mr-1 font-semibold text-[10px]">STATUS:</span>
        {[
          { id: "", label: "ALL STATUS" },
          { id: "new", label: "NEW" },
          { id: "acknowledged", label: "ACKNOWLEDGED" },
          { id: "resolved", label: "RESOLVED" },
          { id: "false_positive", label: "FALSE POSITIVE" },
        ].map((s) => (
          <button
            key={s.id}
            onClick={() => setFilter({ ...filter, status: s.id })}
            className={`px-2 py-1 rounded-[3px] uppercase transition-all cursor-pointer text-[10px] ${
              filter.status === s.id
                ? "bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-400 shadow-[0_0_8px_rgba(0,229,255,0.15)]"
                : "text-slate-400 hover:text-white bg-[#060913] border border-[#162035]"
            }`}
          >
            {s.label}
          </button>
        ))}

        <div className="h-3.5 w-px bg-[#162035] mx-1 hidden sm:block" />

        <span className="text-slate-400 uppercase mr-1 font-semibold text-[10px]">SEVERITY:</span>
        {[
          { id: "", label: "ALL" },
          { id: "critical", label: "CRITICAL (P1)" },
          { id: "high", label: "HIGH (P2)" },
          { id: "medium", label: "MEDIUM (P3)" },
          { id: "low", label: "LOW (P4)" },
        ].map((sev) => (
          <button
            key={sev.id}
            onClick={() => setFilter({ ...filter, severity: sev.id })}
            className={`px-2 py-1 rounded-[3px] uppercase transition-all cursor-pointer text-[10px] ${
              filter.severity === sev.id
                ? "bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-400 shadow-[0_0_8px_rgba(0,229,255,0.15)]"
                : "text-slate-400 hover:text-white bg-[#060913] border border-[#162035]"
            }`}
          >
            {sev.label}
          </button>
        ))}
      </div>

      {/* Incident Matrix Table */}
      <div className="tactical-panel overflow-hidden">
        {loading && alerts.length === 0 ? (
          <div className="p-16 text-center text-slate-400 font-mono text-xs">
            Scanning perimeter incident ledger...
          </div>
        ) : alerts.length === 0 ? (
          <div className="p-14 text-center text-slate-400 space-y-2.5">
            <div className="w-10 h-10 rounded-[4px] bg-[#090e1b] border border-[#162035] flex items-center justify-center mx-auto text-emerald-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-sm font-bold text-slate-100 font-mono uppercase tracking-wider">
              No Security Incidents In Active Queue
            </p>
            <p className="text-[11px] text-slate-400 max-w-md mx-auto font-mono leading-relaxed">
              Perimeter is secure. Any boundary crossings or suspicious activity detected by Edge AI will be logged and dispatched here in real-time.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-[#070b16] text-slate-400 border-b border-[#162035] uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="py-2.5 px-3.5">INCIDENT ID</th>
                  <th className="py-2.5 px-3.5">PRIORITY</th>
                  <th className="py-2.5 px-3.5">TYPE</th>
                  <th className="py-2.5 px-3.5">SUMMARY & ZONE</th>
                  <th className="py-2.5 px-3.5">EVIDENCE</th>
                  <th className="py-2.5 px-3.5">STATUS</th>
                  <th className="py-2.5 px-3.5">TIME (UTC)</th>
                  <th className="py-2.5 px-3.5 text-right">COMMAND ACTIONS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#162035]">
                {alerts.map((alert) => {
                  const clipPath = getClipUrl(alert);
                  const isBreach = alert.alert_type === "fence_breach";
                  const isCritical = alert.severity === "critical" && alert.status === "new";

                  return (
                    <tr
                      key={alert.id}
                      className={`hover:bg-[#0c1324] transition-colors ${
                        isCritical ? "bg-rose-950/20 border-l-2 border-l-rose-500" : ""
                      }`}
                    >
                      <td className="py-2.5 px-3.5 font-bold text-cyan-400 font-mono-tabular">
                        #{alert.id}
                      </td>
                      <td className="py-2.5 px-3.5">
                        <span className={`badge-status ${sevBadges[alert.severity] || "badge-medium"}`}>
                          {alert.severity}
                        </span>
                      </td>
                      <td className="py-2.5 px-3.5 font-semibold text-slate-200 uppercase text-[11px]">
                        {alert.alert_type.replace("_", " ")}
                      </td>
                      <td className="py-2.5 px-3.5 text-slate-200 max-w-sm">
                        <span className="font-sans font-medium text-slate-100 text-xs">
                          {alert.message || alert.alert_type}
                        </span>
                        {isBreach && !!alert.data_json?.zone_name && (
                          <div className="text-[10px] text-cyan-400 font-mono mt-0.5">
                            ZONE: {String(alert.data_json.zone_name)} | TARGET #{String(alert.data_json.track_id ?? "?")}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-3.5">
                        {clipPath ? (
                          <button
                            onClick={() => openAlertModal(alert)}
                            className="btn-tactical-primary text-[10px] py-1 px-2 font-mono"
                          >
                            ▶ REPLAY CLIP
                          </button>
                        ) : (
                          <button
                            onClick={() => openAlertModal(alert)}
                            className="btn-tactical-outline text-[10px] py-1 px-2 font-mono text-slate-400"
                          >
                            📷 VIEW SNAPSHOT
                          </button>
                        )}
                      </td>
                      <td className="py-2.5 px-3.5">
                        <span className="px-1.5 py-0.5 rounded-[2px] text-[10px] font-bold uppercase bg-[#090e1b] border border-[#162035] text-slate-300">
                          {alert.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="py-2.5 px-3.5 text-slate-400 text-[11px] font-mono-tabular">
                        {alert.created_at ? new Date(alert.created_at).toUTCString().slice(17, 25) : "—"}
                      </td>
                      <td className="py-2.5 px-3.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {alert.status === "new" && (
                            <button
                              onClick={() => handleAction(alert.id, "acknowledged")}
                              className="px-2 py-0.5 rounded-[2px] bg-sky-950/80 hover:bg-sky-900 border border-sky-700/60 text-sky-300 text-[9px] font-mono uppercase cursor-pointer"
                            >
                              ACK
                            </button>
                          )}
                          {alert.status !== "resolved" && (
                            <button
                              onClick={() => handleAction(alert.id, "resolved")}
                              className="px-2 py-0.5 rounded-[2px] bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-700/60 text-emerald-300 text-[9px] font-mono uppercase cursor-pointer"
                            >
                              RESOLVE
                            </button>
                          )}
                          {alert.status !== "false_positive" && (
                            <button
                              onClick={() => handleAction(alert.id, "false_positive")}
                              className="px-2 py-0.5 rounded-[2px] bg-[#090e1b] hover:bg-[#121b30] border border-[#162035] text-slate-400 text-[9px] font-mono uppercase cursor-pointer"
                            >
                              FALSE POS
                            </button>
                          )}
                          <button
                            onClick={() => handleDeleteSingle(alert.id)}
                            title="Delete unwanted alert"
                            className="px-1.5 py-0.5 rounded-[2px] bg-rose-950/40 hover:bg-rose-900 border border-rose-800/50 text-rose-400 hover:text-rose-200 text-[10px] font-mono cursor-pointer"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Incident Detail / Video Clip Modal */}
      {selectedAlert && (
        <div className="defense-modal-backdrop">
          <div className="defense-modal max-w-2xl p-5 space-y-3.5">
            <div className="flex items-center justify-between border-b border-[#162035] pb-2.5">
              <div className="flex items-center gap-2">
                <span className={`badge-status ${sevBadges[selectedAlert.severity] || "badge-medium"}`}>
                  {selectedAlert.severity}
                </span>
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-100 font-mono">
                  Incident #{selectedAlert.id} Evidence Clip
                </h2>
              </div>
              <button
                onClick={() => setSelectedAlert(null)}
                className="text-slate-400 hover:text-white text-sm font-bold font-mono cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Video Player / Thumbnail */}
            <div className="rounded-[4px] overflow-hidden bg-black aspect-video border border-[#162035] flex items-center justify-center relative tactical-hud">
              <div className="corner-bracket-tl"></div>
              <div className="corner-bracket-tr"></div>
              <div className="corner-bracket-bl"></div>
              <div className="corner-bracket-br"></div>

              {getClipUrl(selectedAlert) ? (
                <>
                  <video
                    key={`${selectedAlert.id}-${videoRetryKey}`}
                    controls
                    autoPlay
                    playsInline
                    muted
                    preload="auto"
                    className={`w-full h-full object-contain ${videoBuffering ? "hidden" : "block"}`}
                    onLoadedData={() => setVideoBuffering(false)}
                    onWaiting={() => setVideoBuffering(true)}
                    onPlaying={() => setVideoBuffering(false)}
                    onError={() => {
                      if (videoRetryKey < 3) {
                        setVideoBuffering(true);
                        setTimeout(() => setVideoRetryKey((k) => k + 1), 1500);
                      } else {
                        setVideoBuffering(false);
                      }
                    }}
                    src={getMediaUrl(getClipUrl(selectedAlert)!)}
                  >
                    Your browser does not support HTML5 video playback.
                  </video>
                  {videoBuffering && (
                    <div className="text-center p-8 text-cyan-400 font-mono text-xs">
                      <div className="inline-block animate-spin text-2xl mb-2 text-cyan-400">⟳</div>
                      <p className="font-bold text-xs tracking-wider text-white">CAPTURING POST-INCIDENT FOOTAGE...</p>
                      <p className="text-slate-400 text-[11px] mt-1">
                        Finalizing 7-8s tactical evidence clip (~3.5s before + ~4.0s after touch).
                      </p>
                      <p className="text-[10px] text-cyan-400 mt-2 font-semibold font-mono-tabular">
                        Auto-playing shortly (attempt {videoRetryKey + 1}/7)...
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center p-8 text-slate-400 font-mono text-xs">
                  <p className="text-xl mb-1.5">📹</p>
                  <p className="text-slate-200">No video clip attached to this record.</p>
                  <p className="text-[10px] text-slate-500 mt-1">Live buffer frame snapshot stored in ledger.</p>
                </div>
              )}
            </div>

            {/* Incident Summary Info */}
            <div className="p-2.5 rounded-[4px] bg-[#080d1a] border border-[#162035] space-y-1 text-xs font-mono">
              <div className="flex justify-between text-slate-400">
                <span>Incident Type:</span>
                <span className="text-cyan-400 font-bold uppercase">{selectedAlert.alert_type}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Message:</span>
                <span className="text-slate-200">{selectedAlert.message}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Status:</span>
                <span className="text-emerald-400 uppercase font-bold">{selectedAlert.status}</span>
              </div>
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-[#162035]">
              {selectedAlert.status !== "resolved" && (
                <button
                  onClick={() => handleAction(selectedAlert.id, "resolved")}
                  className="btn-tactical-success text-xs"
                >
                  ✓ Mark Resolved
                </button>
              )}
              <button
                onClick={() => setSelectedAlert(null)}
                className="btn-tactical-outline text-xs"
              >
                Close Evidence Viewer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
