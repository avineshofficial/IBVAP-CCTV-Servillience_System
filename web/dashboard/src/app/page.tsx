"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  getStats,
  getAlerts,
  getCameras,
  getEvents,
  connectAlertWebSocket,
} from "@/lib/api";
import type { DashboardStats, Alert, Camera, DetectionEvent } from "@/lib/api";
import LiveCameraPlayer from "@/components/LiveCameraPlayer";
import TacticalLiveMap from "@/components/TacticalLiveMap";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [selectedCamera, setSelectedCamera] = useState<Camera | null>(null);
  const [rightPanelView, setRightPanelView] = useState<"map" | "ledger">("map");
  const [isMapExpanded, setIsMapExpanded] = useState<boolean>(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<string>("");

  useEffect(() => {
    let isSubscribed = true;

    async function fetchTelemetry() {
      try {
        const [s, a, c, e] = await Promise.all([
          getStats(),
          getAlerts({ limit: "10" }),
          getCameras(),
          getEvents({ limit: "15" }),
        ]);
        if (isSubscribed) {
          setStats(s);
          setAlerts(Array.isArray(a) ? a : []);
          setCameras(Array.isArray(c) ? c : []);
          setEvents(Array.isArray(e) ? e : []);
          setLastRefreshed(new Date().toLocaleTimeString("en-GB", { hour12: false }));
        }
      } catch (err) {
        console.error("Dashboard telemetry error:", err);
      }
    }

    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 3000);

    const ws = connectAlertWebSocket((data) => {
      setWsConnected(true);
      if (data.type === "new_alerts" || data.type === "alert_updated") {
        fetchTelemetry();
      }
    });

    return () => {
      isSubscribed = false;
      clearInterval(interval);
      ws?.close();
    };
  }, []);

  // Active main camera for live surveillance view (can be switched by clicking map nodes)
  const primaryCamera =
    selectedCamera ||
    (cameras.length > 0
      ? cameras[0]
      : ({
          id: 1,
          camera_uid: "cam_01",
          name: "Primary Optical Sensor (Lenovo 300 FHD Live)",
          status: "online",
        } as Camera));

  const criticalAlerts = alerts.filter(
    (a) => a.severity === "critical" && a.status === "new"
  );
  const hasCritical = criticalAlerts.length > 0;

  const formatUptime = (seconds?: number) => {
    if (!seconds) return "00h 00m";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m`;
  };

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      {/* Priority Threat Emergency Banner */}
      {hasCritical && (
        <div className="p-3.5 rounded-[4px] border border-rose-500/80 bg-rose-950/40 backdrop-blur-md shadow-[0_0_20px_rgba(244,63,94,0.25)] flex flex-wrap items-center justify-between gap-3 animate-pulse">
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_10px_#f43f5e] animate-ping shrink-0"></span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-rose-300 bg-rose-950/80 px-1.5 py-0.5 rounded border border-rose-500/40">
                  PRIORITY-1 BREACH
                </span>
                <span className="text-xs font-mono text-rose-200">
                  SECTOR: BOP ALPHA · LINE CROSSING RECORDED
                </span>
              </div>
              <p className="text-sm font-semibold text-white mt-1">
                {criticalAlerts[0].message || "Unauthorized perimeter penetration detected on active camera sensor"}
              </p>
            </div>
          </div>
          <Link
            href="/alerts"
            className="btn-tactical-danger text-xs uppercase font-mono tracking-wider shrink-0"
          >
            Acknowledge & Triage Incident →
          </Link>
        </div>
      )}

      {/* Top Mission Strip: Operational Title & Connectivity Pulse */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#162035] pb-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_6px_#00e5ff]"></span>
            <h1 className="text-sm font-bold uppercase tracking-widest text-slate-100 font-mono">
              TACTICAL SURVEILLANCE OPERATIONS
            </h1>
          </div>
          <span className="text-slate-600">/</span>
          <span className="text-xs font-mono text-slate-400">
            SECTOR: <strong className="text-slate-200">BOP ALPHA (SSB IN-NPL)</strong>
          </span>
          <span className="badge-status badge-online hidden sm:inline-flex">
            <span className="status-pip status-pip-online"></span> SENTINEL LIVE
          </span>
        </div>

        <div className="flex items-center gap-2.5 text-xs font-mono">
          <div className="flex items-center gap-2 px-2.5 py-1 rounded-[3px] bg-[#090e1b] border border-[#162035]">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                wsConnected ? "bg-emerald-400 shadow-[0_0_6px_#10b981]" : "bg-amber-400 animate-ping"
              }`}
            ></span>
            <span className={wsConnected ? "text-emerald-400 font-bold text-[11px]" : "text-amber-400 text-[11px]"}>
              {wsConnected ? "STREAM TELEMETRY ACTIVE" : "CONNECTING TO SIGNAL..."}
            </span>
          </div>
          <span className="text-slate-400 text-[11px] hidden md:inline font-mono-tabular">
            REFRESH: {lastRefreshed || "SYNCING"}
          </span>
        </div>
      </div>

      {/* Integrated C4ISR Operational Telemetry Ribbon */}
      <div className="telemetry-ribbon grid-cols-2 lg:grid-cols-4">
        {/* Metric 1: Optical Sensors */}
        <div className="telemetry-cell">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-semibold">
              OPTICAL SENSORS
            </span>
            <span className="text-[9px] font-mono font-bold text-cyan-300 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/40">
              CCTV / USB
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-white font-mono-tabular">
              {stats?.cameras_online ?? 0}
            </span>
            <span className="text-xs font-mono text-slate-400">
              / {stats?.total_cameras ?? 1} ACTIVE
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono text-emerald-400">
            <span className="w-1 h-1 rounded-full bg-emerald-400"></span>
            <span>100% SENSOR HEALTH</span>
          </div>
        </div>

        {/* Metric 2: AI Detections */}
        <div className="telemetry-cell">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-semibold">
              INFERENCE TARGETS
            </span>
            <span className="text-[9px] font-mono font-bold text-sky-300 bg-sky-950/60 px-1.5 py-0.5 rounded border border-sky-800/40">
              YOLOv11n
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-sky-400 font-mono-tabular">
              {stats?.total_events ?? events.length}
            </span>
            <span className="text-xs font-mono text-slate-400">TRACKED</span>
          </div>
          <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono text-slate-400">
            <span>BYTETRACK CONTINUOUS POOL</span>
          </div>
        </div>

        {/* Metric 3: Threat Queue */}
        <div className="telemetry-cell">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-semibold">
              INCIDENT QUEUE
            </span>
            <span
              className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                (stats?.critical_alerts ?? 0) > 0
                  ? "bg-rose-950/80 text-rose-300 border-rose-800/60"
                  : "bg-slate-900 text-slate-400 border-slate-700/60"
              }`}
            >
              {(stats?.critical_alerts ?? 0) > 0 ? "BREACH ALERT" : "STANDBY"}
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span
              className={`text-2xl font-bold font-mono font-mono-tabular ${
                (stats?.active_alerts ?? alerts.length) > 0 ? "text-rose-400" : "text-white"
              }`}
            >
              {stats?.active_alerts ?? alerts.length}
            </span>
            <span className="text-xs font-mono text-slate-400">PENDING</span>
          </div>
          <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono text-slate-400">
            <span>{stats?.critical_alerts ?? 0} CRITICAL · {stats?.active_alerts ?? alerts.length} TOTAL</span>
          </div>
        </div>

        {/* Metric 4: System Uptime */}
        <div className="telemetry-cell">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-semibold">
              GRID UPTIME
            </span>
            <span className="text-[9px] font-mono font-bold text-emerald-300 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/40">
              NOMINAL
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-emerald-400 font-mono-tabular">
              {stats ? formatUptime(stats.system_uptime) : "00h 00m"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono text-slate-400">
            <span>ZERO-DOWNTIME EDGE ARCH</span>
          </div>
        </div>
      </div>

      {/* Main Tactical Split View: Primary Camera HUD + Tactical Map Overview / Track Ledger */}
      <div className={`grid grid-cols-1 ${isMapExpanded ? "lg:grid-cols-1" : "lg:grid-cols-12"} gap-4 items-start`}>
        {/* Left Column: Primary Optical Sensor Viewport (7 cols = 60% on large screens) */}
        <div className={`${isMapExpanded ? "hidden" : "lg:col-span-7"} space-y-3`}>
          <div className="tactical-panel p-3.5 space-y-3">
            {/* HUD Viewport Header */}
            <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[#162035] pb-2.5 text-xs font-mono">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse"></span>
                <span className="font-bold text-white uppercase tracking-wider text-xs">
                  {primaryCamera.name}
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-cyan-400 font-bold bg-[#0c1424] px-1.5 py-0.2 rounded border border-cyan-800/40 text-[11px]">
                  {primaryCamera.camera_uid.toUpperCase()}
                </span>
                <span className="text-slate-400 text-[10px] hidden sm:inline">
                  SSB BOP ALPHA
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="px-1.5 py-0.5 rounded-[2px] bg-[#090f1d] border border-cyan-800/50 text-cyan-300 text-[9px] font-bold">
                  FHD 1080P · 95° WIDE FOV
                </span>
                <span className="px-1.5 py-0.5 rounded-[2px] bg-[#090f1d] border border-emerald-800/50 text-emerald-400 text-[9px] font-bold">
                  25 FPS FLUENT
                </span>
                <span className="px-1.5 py-0.5 rounded-[2px] bg-[#090f1d] border border-slate-700/50 text-slate-300 text-[9px] font-bold">
                  AI BOUNDING BOX ON
                </span>
              </div>
            </div>

            {/* Video Player Component */}
            <LiveCameraPlayer
              cameraUid={primaryCamera.camera_uid}
              cameraName={primaryCamera.name}
            />

            {/* Viewport Footer Telemetry & Navigation */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-2 text-xs font-mono text-slate-400 border-t border-[#162035]">
              <div className="flex items-center gap-3 text-[11px]">
                <span>
                  INFERENCE: <strong className="text-slate-200">YOLOv11n (384p)</strong>
                </span>
                <span className="text-slate-600">·</span>
                <span>
                  TRACKER: <strong className="text-slate-200">ByteTrack</strong>
                </span>
                <span className="text-slate-600">·</span>
                <span>
                  BUFFER: <strong className="text-cyan-400">Low-Latency MJPEG</strong>
                </span>
              </div>

              <Link
                href="/cameras"
                className="btn-tactical-outline text-[11px] uppercase tracking-wider py-1 px-2.5"
              >
                Manage Optical Sensors Grid →
              </Link>
            </div>
          </div>
        </div>

        {/* Right Column: Tactical Live Map Overview (5 cols = 40% width) with Mode Switch to Ledger */}
        <div className={`${isMapExpanded ? "w-full" : "lg:col-span-5"} space-y-3`}>
          {/* Dual Mode Switcher: Live Map Overview vs. Track Ledger */}
          <div className="flex items-center justify-between border-b border-[#162035] pb-2">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setRightPanelView("map")}
                className={`px-3 py-1 rounded-[3px] text-xs font-mono font-bold tracking-wider uppercase transition-all flex items-center gap-1.5 cursor-pointer ${
                  rightPanelView === "map"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-400 shadow-[0_0_10px_rgba(0,229,255,0.2)]"
                    : "text-slate-400 hover:text-white bg-[#090e1b] border border-[#162035]"
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                <span>🛰️ LIVE MAP (40%)</span>
                {hasCritical && (
                  <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping"></span>
                )}
              </button>

              <button
                onClick={() => setRightPanelView("ledger")}
                className={`px-3 py-1 rounded-[3px] text-xs font-mono font-bold tracking-wider uppercase transition-all flex items-center gap-1.5 cursor-pointer ${
                  rightPanelView === "ledger"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-400 shadow-[0_0_10px_rgba(0,229,255,0.2)]"
                    : "text-slate-400 hover:text-white bg-[#090e1b] border border-[#162035]"
                }`}
              >
                <span>📋 TRACK LEDGER</span>
                <span className="text-[9px] px-1 rounded bg-[#070b16] text-cyan-300 border border-[#162035] font-mono-tabular">
                  {events.length}
                </span>
              </button>
            </div>

            <span className="text-[10px] font-mono text-slate-400 hidden sm:inline">
              CLICK CAM NODE TO VIEW
            </span>
          </div>

          {/* View 1: Tactical Live Map Overview (Altered to Location Map with Red Alert Blinking) */}
          {rightPanelView === "map" ? (
            <div className="space-y-3">
              <TacticalLiveMap
                cameras={cameras}
                alerts={alerts}
                selectedCameraUid={primaryCamera.camera_uid}
                onSelectCamera={(cam) => setSelectedCamera(cam)}
                isExpanded={isMapExpanded}
                onToggleExpand={() => setIsMapExpanded((prev) => !prev)}
              />

              {/* Compact Detection Feed directly below Map */}
              <div className="tactical-panel p-2.5 text-xs font-mono space-y-1.5">
                <div className="flex items-center justify-between text-[10px] text-slate-400 border-b border-[#162035] pb-1">
                  <span className="font-bold text-slate-300 uppercase">LATEST PERIMETER TARGETS</span>
                  <span className="text-cyan-400">{events.length} RECORDED</span>
                </div>

                <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
                  {events.slice(0, 3).map((ev) => {
                    const isThreat =
                      ev.event_type.toLowerCase().includes("cross") ||
                      ev.event_type.toLowerCase().includes("intrusion");
                    const timeStr = new Date(ev.timestamp * 1000).toLocaleTimeString("en-GB", {
                      hour12: false,
                    });
                    return (
                      <div
                        key={ev.id}
                        className={`p-1.5 rounded-[2px] border flex items-center justify-between text-[11px] ${
                          isThreat
                            ? "bg-rose-950/30 border-rose-800/50 text-rose-200"
                            : "bg-[#090e1b] border-[#162035] text-slate-300"
                        }`}
                      >
                        <div className="flex items-center gap-1.5 truncate">
                          <span
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              isThreat ? "bg-rose-500 animate-ping" : "bg-cyan-400"
                            }`}
                          />
                          <span className="font-bold uppercase text-[10px]">{ev.event_type}</span>
                          {ev.track_id && (
                            <span className="text-[9px] px-1 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/40">
                              #{ev.track_id}
                            </span>
                          )}
                          <span className="text-slate-500 text-[9px]">{ev.camera_uid.toUpperCase()}</span>
                        </div>
                        <span className="text-[9px] text-slate-400 font-mono-tabular shrink-0">
                          {timeStr}
                        </span>
                      </div>
                    );
                  })}
                </div>

                <div className="pt-1 border-t border-[#162035] flex items-center justify-between">
                  <button
                    onClick={() => setRightPanelView("ledger")}
                    className="text-[10px] text-cyan-400 hover:text-cyan-300 cursor-pointer"
                  >
                    View All {events.length} Tracked Events →
                  </button>
                  <Link
                    href="/alerts"
                    className="text-[10px] text-slate-400 hover:text-slate-200"
                  >
                    Open Alert Triage →
                  </Link>
                </div>
              </div>
            </div>
          ) : (
            /* View 2: Full Sentinel Track Ledger (from original view) */
            <div className="tactical-panel p-3.5 space-y-3">
              {/* Ledger Header */}
              <div className="flex items-center justify-between border-b border-[#162035] pb-2.5">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#00e5ff]"></span>
                  <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-slate-100">
                    Sentinel Track Ledger
                  </h2>
                </div>
                <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/40 font-bold">
                  {events.length} LOGGED
                </span>
              </div>

              {/* Track Event Records */}
              <div className="space-y-1.5 max-h-[520px] overflow-y-auto pr-1">
                {events.length === 0 ? (
                  <div className="p-8 text-center text-slate-400 space-y-2.5">
                    <div className="w-9 h-9 rounded bg-[#090f1d] border border-cyan-500/30 flex items-center justify-center mx-auto text-cyan-400">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <circle cx="12" cy="12" r="7" strokeDasharray="3 3" />
                        <circle cx="12" cy="12" r="2" fill="#00e5ff" />
                      </svg>
                    </div>
                    <p className="text-xs font-semibold text-slate-300 font-mono uppercase tracking-wider">
                      SENTINEL SURVEILLANCE ACTIVE
                    </p>
                    <p className="text-[10px] text-slate-400 leading-relaxed font-mono">
                      Optical sensor active on channel {primaryCamera.camera_uid.toUpperCase()}. Neural detections will populate this ledger in real time.
                    </p>
                  </div>
                ) : (
                  events.map((ev) => {
                    const conf = ev.confidence ? Math.round(ev.confidence * 100) : 95;
                    const timeStr = new Date(ev.timestamp * 1000).toLocaleTimeString("en-GB", {
                      hour12: false,
                    });
                    const isThreat =
                      ev.event_type.toLowerCase().includes("cross") ||
                      ev.event_type.toLowerCase().includes("intrusion");

                    return (
                      <div
                        key={ev.id}
                        className={`p-2 rounded-[3px] border transition-colors flex items-center justify-between text-xs font-mono ${
                          isThreat
                            ? "bg-rose-950/30 border-rose-800/50 hover:border-rose-500/60"
                            : "bg-[#090e1b] border-[#162035] hover:border-cyan-500/40"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              isThreat
                                ? "bg-rose-500 shadow-[0_0_6px_#f43f5e]"
                                : "bg-cyan-400 shadow-[0_0_6px_#00e5ff]"
                            }`}
                          ></span>
                          <div className="truncate">
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-slate-200 uppercase text-[11px] truncate">
                                {ev.event_type}
                              </span>
                              {ev.track_id && (
                                <span className="text-[9px] px-1 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/40 font-bold">
                                  #{ev.track_id}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 text-[9px] text-slate-400 mt-0.5">
                              <span>
                                CONF: <strong className="text-slate-300">{conf}%</strong>
                              </span>
                              <span>·</span>
                              <span>{ev.camera_uid.toUpperCase()}</span>
                            </div>
                          </div>
                        </div>

                        <span className="text-[10px] text-slate-400 font-mono-tabular shrink-0 ml-2">
                          {timeStr}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Quick Link to Analytics */}
              <div className="pt-2 border-t border-[#162035]">
                <Link
                  href="/analytics"
                  className="w-full btn-tactical-outline text-[11px] justify-center py-1.5"
                >
                  View Full Threat Intelligence Ledger →
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
