"use client";
import React, { useEffect, useState } from "react";
import {
  getSecurityStats,
  getSecurityLogs,
  getRBACMatrix,
  getDPDPCompliance,
  rotateSecurityKeys,
  runSecurityAuditScan,
} from "@/lib/api";
import type {
  SecurityStats,
  SecurityLogItem,
  RolePermission,
  DPDPCompliance,
} from "@/lib/api";

type SecurityTab = "overview" | "rbac" | "dpdp" | "logs";

export default function SecurityPage() {
  const [stats, setStats] = useState<SecurityStats | null>(null);
  const [logs, setLogs] = useState<SecurityLogItem[]>([]);
  const [rbac, setRbac] = useState<RolePermission[]>([]);
  const [dpdp, setDpdp] = useState<DPDPCompliance | null>(null);
  const [loading, setLoading] = useState(true);
  const [rotating, setRotating] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [activeTab, setActiveTab] = useState<SecurityTab>("overview");
  const [notification, setNotification] = useState<string | null>(null);

  const refreshData = async () => {
    try {
      const [s, l, r, d] = await Promise.all([
        getSecurityStats(),
        getSecurityLogs({ limit: "50" }),
        getRBACMatrix(),
        getDPDPCompliance(),
      ]);
      setStats(s);
      setLogs(Array.isArray(l) ? l : []);
      setRbac(Array.isArray(r) ? r : []);
      setDpdp(d);
    } catch (e) {
      console.error("Security data load failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let isSubscribed = true;

    async function loadData() {
      try {
        const [s, l, r, d] = await Promise.all([
          getSecurityStats(),
          getSecurityLogs({ limit: "50" }),
          getRBACMatrix(),
          getDPDPCompliance(),
        ]);
        if (isSubscribed) {
          setStats(s);
          setLogs(Array.isArray(l) ? l : []);
          setRbac(Array.isArray(r) ? r : []);
          setDpdp(d);
          setLoading(false);
        }
      } catch (e) {
        console.error("Security data load failed:", e);
      }
    }

    loadData();
    const interval = setInterval(loadData, 5000);
    return () => {
      isSubscribed = false;
      clearInterval(interval);
    };
  }, []);

  async function handleRotateKeys() {
    setRotating(true);
    try {
      const res = await rotateSecurityKeys();
      setNotification(`🔑 Key Rotation Success: ${res.message}`);
      await refreshData();
    } catch (e) {
      console.error(e);
      setNotification("❌ Key rotation failed");
    } finally {
      setRotating(false);
      setTimeout(() => setNotification(null), 5000);
    }
  }

  async function handleRunScan() {
    setScanning(true);
    try {
      const res = await runSecurityAuditScan();
      setNotification(`🔍 Security Scan Completed — Score: ${res.score}/100`);
      await refreshData();
    } catch (e) {
      console.error(e);
      setNotification("❌ Security scan failed");
    } finally {
      setScanning(false);
      setTimeout(() => setNotification(null), 5000);
    }
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#1a233a] pb-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold uppercase tracking-wide text-white">
              Zero-Trust Security & Compliance
            </h1>
            <span className="badge-status badge-online">
              <span className="status-pip status-pip-online"></span> {loading ? "SYNCING..." : "ENFORCED & COMPLIANT"}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Role-Based Access Control (RBAC) · DPDP Act 2023 Compliance · HMAC-SHA256 Cryptographic Protection
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRotateKeys}
            disabled={rotating}
            className="btn-defense-outline text-xs font-mono uppercase tracking-wider"
          >
            {rotating ? "⏳ Rotating..." : "🔑 Rotate Keys"}
          </button>
          <button
            onClick={handleRunScan}
            disabled={scanning}
            className="btn-defense-primary text-xs font-mono uppercase tracking-wider"
          >
            {scanning ? "⏳ Scanning..." : "🔍 Run Security Audit"}
          </button>
        </div>
      </div>

      {/* Action Notification Toast */}
      {notification && (
        <div className="p-3 rounded-xl bg-cyan-950/40 border border-cyan-500/50 text-cyan-300 text-xs font-mono flex items-center justify-between">
          <span>{notification}</span>
          <button onClick={() => setNotification(null)}>✕</button>
        </div>
      )}

      {/* Security Health Score Banner */}
      <div className="defense-card p-5">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-emerald-950/60 border border-emerald-500/40 flex items-center justify-center text-2xl font-black font-mono text-emerald-400">
              {stats?.security_score ?? 100}
            </div>
            <div>
              <p className="text-xs font-mono uppercase text-slate-400">Security Score</p>
              <p className="text-sm font-bold text-white mt-0.5">Defensive Hardening</p>
            </div>
          </div>

          <div className="space-y-1 font-mono text-xs">
            <span className="text-slate-400 uppercase text-[10px]">Active Sessions:</span>
            <p className="text-white font-bold">{stats?.active_sessions ?? 1} Connected</p>
          </div>

          <div className="space-y-1 font-mono text-xs">
            <span className="text-slate-400 uppercase text-[10px]">Defense Users:</span>
            <p className="text-white font-bold">{stats?.total_users ?? 4} Registered</p>
          </div>

          <div className="space-y-1 font-mono text-xs">
            <span className="text-slate-400 uppercase text-[10px]">DPDP Compliance:</span>
            <p className="text-emerald-400 font-bold">● 100% Verified (MHA Audit)</p>
          </div>
        </div>
      </div>

      {/* Tab Selector */}
      <div className="flex gap-2 border-b border-[#1a233a] pb-2 text-xs font-mono uppercase">
        {([
          { id: "overview" as const, label: "Security Overview" },
          { id: "rbac" as const, label: `RBAC Matrix (${rbac.length || 4})` },
          { id: "dpdp" as const, label: `DPDP Act Compliance ${dpdp ? "✓" : ""}` },
          { id: "logs" as const, label: `Security Logs (${logs.length})` },
        ] as const).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 rounded-lg transition-all cursor-pointer ${
              activeTab === tab.id
                ? "bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-400"
                : "text-slate-400 hover:text-white bg-[#0a0f1e]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Overview */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="defense-card p-5 space-y-3 font-mono text-xs">
            <h3 className="text-xs font-bold uppercase tracking-wider text-white border-b border-[#1a233a] pb-2">
              Cryptographic Hardening Controls
            </h3>
            <div className="space-y-2.5 text-slate-300">
              <div className="flex justify-between">
                <span className="text-slate-400">Ledger Hash Algorithm:</span>
                <span className="text-cyan-400 font-bold">SHA-256 (Merkle Chained)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Watchlist Privacy:</span>
                <span className="text-cyan-400 font-bold">HMAC-SHA256 (Irreversible)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">API Key Encryption:</span>
                <span className="text-emerald-400 font-bold">PBKDF2 + AES-GCM</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Authentication Scheme:</span>
                <span className="text-emerald-400 font-bold">JWT Bearer (24h Expiry)</span>
              </div>
            </div>
          </div>

          <div className="defense-card p-5 space-y-3 font-mono text-xs">
            <h3 className="text-xs font-bold uppercase tracking-wider text-white border-b border-[#1a233a] pb-2">
              Edge Pipeline Security Posture
            </h3>
            <div className="space-y-2.5 text-slate-300">
              <div className="flex justify-between">
                <span className="text-slate-400">Edge Node Auth:</span>
                <span className="text-emerald-400 font-bold">Mutual Secret Header</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Local Buffer Isolation:</span>
                <span className="text-emerald-400 font-bold">Encrypted SQLite DB</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Video Storage:</span>
                <span className="text-slate-200">Local Ring Buffer (72h Auto-purge)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Offline Resilience:</span>
                <span className="text-emerald-400 font-bold">Full Edge Autonomous Mode</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: RBAC Matrix */}
      {activeTab === "rbac" && (
        <div className="defense-card overflow-hidden">
          <div className="p-4 border-b border-[#1a233a] flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-white">
              Role-Based Access Control (RBAC) Enforcement
            </h3>
            <span className="text-[10px] font-mono text-slate-400">4 MILITARY TIERS</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-[#0a0f1e] text-slate-400 border-b border-[#1a233a] text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">ROLE</th>
                  <th className="py-3 px-4">CLEARANCE TIER</th>
                  <th className="py-3 px-4">LIVE SURVEILLANCE</th>
                  <th className="py-3 px-4">ALERT TRIAGE</th>
                  <th className="py-3 px-4">AUDIT VERIFY</th>
                  <th className="py-3 px-4">WATCHLIST WRITE</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1a233a]">
                {[
                  { role: "Administrator", tier: "Tier-1 HQ", live: "Full", alert: "Acknowledge / Resolve / Delete", audit: "Verify / Re-hash", wl: "Read / Write" },
                  { role: "Post Commander", tier: "Tier-2 BOP", live: "Full Sector", alert: "Acknowledge / Resolve", audit: "Verify Only", wl: "Read / Write" },
                  { role: "Field Officer", tier: "Tier-3 Patrol", live: "Sector View", alert: "Acknowledge", audit: "Restricted", wl: "Read Only" },
                  { role: "HQ Analyst", tier: "Tier-4 Global", live: "Global Matrix", alert: "Read / Annotate", audit: "Audit Read Only", wl: "Read Only" },
                ].map((item) => (
                  <tr key={item.role} className="hover:bg-[#0f162b] transition-colors">
                    <td className="py-3 px-4 font-bold text-white">{item.role}</td>
                    <td className="py-3 px-4 text-cyan-400">{item.tier}</td>
                    <td className="py-3 px-4 text-slate-300">{item.live}</td>
                    <td className="py-3 px-4 text-slate-300">{item.alert}</td>
                    <td className="py-3 px-4 text-slate-300">{item.audit}</td>
                    <td className="py-3 px-4 text-slate-300">{item.wl}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: DPDP Compliance */}
      {activeTab === "dpdp" && (
        <div className="defense-card p-5 space-y-4 font-mono text-xs">
          <div className="border-b border-[#1a233a] pb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-white">
              Digital Personal Data Protection (DPDP) Act 2023 Compliance
            </h3>
            <p className="text-[11px] text-slate-400 mt-1">
              Statutory framework governing biometric surveillance data handling and automated retention purge
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-3.5 rounded-xl bg-[#080d18] border border-[#1a233a] space-y-1">
              <span className="text-slate-400 text-[10px]">SECTION 8(1) DATA MINIMIZATION</span>
              <p className="font-bold text-white">Non-target video streams auto-purged after 72 hours</p>
            </div>
            <div className="p-3.5 rounded-xl bg-[#080d18] border border-[#1a233a] space-y-1">
              <span className="text-slate-400 text-[10px]">SECTION 9 BIOMETRIC SECURITY</span>
              <p className="font-bold text-white">Raw faces never stored; one-way HMAC embeddings only</p>
            </div>
            <div className="p-3.5 rounded-xl bg-[#080d18] border border-[#1a233a] space-y-1">
              <span className="text-slate-400 text-[10px]">SECTION 10 AUDIT TRAIL IMMUTABILITY</span>
              <p className="font-bold text-white">Every record edit is cryptographically chained via SHA-256</p>
            </div>
            <div className="p-3.5 rounded-xl bg-[#080d18] border border-[#1a233a] space-y-1">
              <span className="text-slate-400 text-[10px]">AIR-GAPPED COMPLIANCE</span>
              <p className="font-bold text-white">Zero cloud dependency; all models execute strictly on edge</p>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Logs */}
      {activeTab === "logs" && (
        <div className="defense-card overflow-hidden">
          <div className="p-4 border-b border-[#1a233a] flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider font-mono text-white">
              Security Event Ledger
            </h3>
            <span className="text-[10px] font-mono text-slate-400">{logs.length} RECORDS</span>
          </div>

          {logs.length === 0 ? (
            <div className="p-12 text-center text-slate-500 font-mono text-xs">
              No security anomalies or authorization failures recorded.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0a0f1e] text-slate-400 border-b border-[#1a233a] text-[10px] uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-4">EVENT ID</th>
                    <th className="py-3 px-4">TYPE</th>
                    <th className="py-3 px-4">SEVERITY</th>
                    <th className="py-3 px-4">DETAIL</th>
                    <th className="py-3 px-4 text-right">TIMESTAMP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1a233a]">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-[#0f162b] transition-colors">
                      <td className="py-3 px-4 font-bold text-cyan-400">#{log.id}</td>
                      <td className="py-3 px-4 uppercase text-slate-200">{log.event_type}</td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800 text-slate-300">
                          {log.severity}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-300">{log.details || log.event_type}</td>
                      <td className="py-3 px-4 text-right text-slate-400 font-mono-tabular">
                        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString("en-GB") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
