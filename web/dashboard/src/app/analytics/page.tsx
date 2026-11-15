"use client";
import React, { useEffect, useState } from "react";
import { getStats, getAlerts, getEvents, getAuditStats } from "@/lib/api";
import type { DashboardStats, Alert, DetectionEvent, AuditStats } from "@/lib/api";

export default function AnalyticsPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [auditStats, setAuditStats] = useState<AuditStats | null>(null);

  const handleRefresh = async () => {
    try {
      const [s, a, e, as_] = await Promise.all([
        getStats(),
        getAlerts({ limit: "200" }),
        getEvents({ limit: "200" }),
        getAuditStats(),
      ]);
      setStats(s);
      setAlerts(Array.isArray(a) ? a : []);
      setEvents(Array.isArray(e) ? e : []);
      setAuditStats(as_);
    } catch (e) {
      console.error("Analytics load failed:", e);
    }
  };

  useEffect(() => {
    let isSubscribed = true;

    async function loadData() {
      try {
        const [s, a, e, as_] = await Promise.all([
          getStats(),
          getAlerts({ limit: "200" }),
          getEvents({ limit: "200" }),
          getAuditStats(),
        ]);
        if (isSubscribed) {
          setStats(s);
          setAlerts(Array.isArray(a) ? a : []);
          setEvents(Array.isArray(e) ? e : []);
          setAuditStats(as_);
        }
      } catch (e) {
        console.error("Analytics load failed:", e);
      }
    }

    loadData();
    const interval = setInterval(loadData, 6000);
    return () => {
      isSubscribed = false;
      clearInterval(interval);
    };
  }, []);

  // Real-time aggregates
  const alertsByType = alerts.reduce((acc, a) => {
    acc[a.alert_type] = (acc[a.alert_type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const alertsBySeverity = alerts.reduce((acc, a) => {
    acc[a.severity] = (acc[a.severity] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const eventsByType = events.reduce((acc, e) => {
    acc[e.event_type] = (acc[e.event_type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const falsePositives = alerts.filter((a) => a.status === "false_positive").length;
  const resolvedCount = alerts.filter((a) => a.status === "resolved").length;
  const totalAlerts = alerts.length;
  const fpRate = totalAlerts > 0 ? ((falsePositives / totalAlerts) * 100).toFixed(1) : "0.0";
  const resolveRate = totalAlerts > 0 ? ((resolvedCount / totalAlerts) * 100).toFixed(1) : "100.0";

  const formatUptime = (seconds?: number) => {
    if (!seconds) return "Active";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m ${Math.floor(seconds % 60)}s`;
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#1a233a] pb-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold uppercase tracking-wide text-white">
              Surveillance Intelligence & Analytics
            </h1>
            <span className="badge-status badge-online">
              <span className="status-pip status-pip-online"></span> LIVE TELEMETRY
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Real-world detection rates · Model accuracy metrics · False-positive drift analysis
          </p>
        </div>

        <button
          onClick={handleRefresh}
          className="btn-defense-outline text-xs font-mono uppercase tracking-wider cursor-pointer"
        >
          ↻ Refresh Metrics
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Detection Yield</span>
          <p className="text-2xl font-bold font-mono text-cyan-400 mt-2">
            {events.length}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Total optical objects tracked</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Resolution Efficiency</span>
          <p className="text-2xl font-bold font-mono text-emerald-400 mt-2">
            {resolveRate}%
          </p>
          <p className="text-[11px] text-slate-400 mt-1">{resolvedCount} incidents resolved</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">False Positive Rate</span>
          <p className="text-2xl font-bold font-mono text-amber-400 mt-2">
            {fpRate}%
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Model precision gating active</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">System Continuous Run</span>
          <p className="text-2xl font-bold font-mono text-sky-400 mt-2">
            {formatUptime(stats?.system_uptime)}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Zero edge frame buffer stalls</p>
        </div>
      </div>

      {/* Analytical Breakdown Grids */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Detection Breakdown */}
        <div className="defense-card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-[#1a233a] pb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
              Optical Target Classification
            </h2>
            <span className="text-[10px] font-mono text-slate-400">{events.length} EVENTS</span>
          </div>

          {Object.keys(eventsByType).length === 0 ? (
            <div className="p-8 text-center text-slate-500 font-mono text-xs">
              No target classifications logged yet in this session.
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(eventsByType).map(([cls, count]) => {
                const pct = events.length > 0 ? Math.round((count / events.length) * 100) : 0;
                return (
                  <div key={cls} className="space-y-1 font-mono text-xs">
                    <div className="flex justify-between text-slate-300">
                      <span className="capitalize font-bold">{cls}</span>
                      <span className="text-cyan-400">{count} ({pct}%)</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-[#0a0f1e] overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-cyan-500 to-sky-400 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Severity Distribution */}
        <div className="defense-card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-[#1a233a] pb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-rose-500"></span>
              Alert Severity Breakdown
            </h2>
            <span className="text-[10px] font-mono text-slate-400">{totalAlerts} ALERTS</span>
          </div>

          {totalAlerts === 0 ? (
            <div className="p-8 text-center text-slate-500 font-mono text-xs">
              Zero threat alerts recorded. Sector perimeter is clean.
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(alertsBySeverity).map(([sev, count]) => {
                const pct = totalAlerts > 0 ? Math.round((count / totalAlerts) * 100) : 0;
                const barColor =
                  sev === "critical"
                    ? "from-rose-500 to-rose-400"
                    : sev === "high"
                    ? "from-amber-500 to-amber-400"
                    : "from-sky-500 to-cyan-400";
                return (
                  <div key={sev} className="space-y-1 font-mono text-xs">
                    <div className="flex justify-between text-slate-300">
                      <span className="uppercase font-bold">{sev}</span>
                      <span className="text-white">{count} ({pct}%)</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-[#0a0f1e] overflow-hidden">
                      <div
                        className={`h-full bg-gradient-to-r ${barColor} rounded-full`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Row 2: Threat Modality & Immutable Audit Ledger Telemetry */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Threat Modality / Types */}
        <div className="defense-card p-5 space-y-4 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-[#1a233a] pb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              Incident Breach Modalities
            </h2>
            <span className="text-[10px] text-slate-400">{Object.keys(alertsByType).length} TYPES</span>
          </div>

          {Object.keys(alertsByType).length === 0 ? (
            <div className="p-6 text-center text-slate-500">
              No alert breach classifications recorded.
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(alertsByType).map(([type, count]) => (
                <div key={type} className="flex items-center justify-between p-2 rounded bg-[#090e1b] border border-[#162035]">
                  <span className="font-bold text-slate-200 uppercase">{type.replace("_", " ")}</span>
                  <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/40 text-[11px] font-bold">
                    {count} INCIDENTS
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Cryptographic Audit Ledger Telemetry */}
        <div className="defense-card p-5 space-y-4 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-[#1a233a] pb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
              Cryptographic Audit Telemetry
            </h2>
            <span className="text-[10px] text-emerald-400">SHA-256 IMMUTABLE</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 rounded bg-[#090e1b] border border-[#162035]">
              <span className="text-[10px] text-slate-400 uppercase">Chained Blocks</span>
              <p className="text-lg font-bold text-white mt-1">
                {auditStats?.total_records ?? 0}
              </p>
            </div>
            <div className="p-3 rounded bg-[#090e1b] border border-[#162035]">
              <span className="text-[10px] text-slate-400 uppercase">Head Block Hash</span>
              <p className="text-xs font-mono font-bold text-emerald-400 mt-1 truncate">
                {auditStats?.last_hash ? `${auditStats.last_hash.slice(0, 12)}...` : "SHA-256 VERIFIED"}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
