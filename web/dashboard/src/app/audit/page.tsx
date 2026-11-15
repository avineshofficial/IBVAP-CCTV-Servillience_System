"use client";
import React, { useEffect, useState } from "react";
import { getAuditChain, verifyFullChain, getAuditStats } from "@/lib/api";
import type { AuditRecord, ChainVerification, AuditStats } from "@/lib/api";

export default function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [verification, setVerification] = useState<ChainVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    let isSubscribed = true;

    async function loadData() {
      try {
        const [r, s] = await Promise.all([getAuditChain(50), getAuditStats()]);
        if (isSubscribed) {
          setRecords(Array.isArray(r) ? r : []);
          setStats(s);
        }
      } catch (e) {
        console.error("Audit load failed:", e);
      }
    }

    loadData();
    const interval = setInterval(loadData, 5000);
    return () => {
      isSubscribed = false;
      clearInterval(interval);
    };
  }, []);

  async function handleVerify() {
    setVerifying(true);
    setVerification(null);
    try {
      const result = await verifyFullChain();
      setVerification(result);
    } catch (e) {
      console.error("Chain verification error:", e);
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#1a233a] pb-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold uppercase tracking-wide text-white">
              SHA-256 Tamper-Evident Hash Ledger
            </h1>
            <span className="badge-status badge-online">
              <span className="status-pip status-pip-online"></span> ZERO-TRUST INTEGRITY
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Cryptographic SHA-256 hash-chaining · Every security event is cryptographically sealed and immutable
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleVerify}
            disabled={verifying}
            className="btn-defense-primary text-xs font-mono uppercase tracking-wider"
          >
            {verifying ? "⏳ Verifying Hashes..." : "🔍 Verify Cryptographic Chain"}
          </button>
        </div>
      </div>

      {/* Verification Result Banner */}
      {verification && (
        <div
          className={`p-4 rounded-xl border backdrop-blur-md flex items-center justify-between text-xs font-mono ${
            verification.verified
              ? "bg-emerald-950/30 border-emerald-500/50 text-emerald-300"
              : "bg-rose-950/30 border-rose-500/50 text-rose-300"
          }`}
        >
          <div className="flex items-center gap-3">
            <span className="text-xl">{verification.verified ? "✅" : "⚠️"}</span>
            <div>
              <p className="font-bold uppercase tracking-wider">
                {verification.verified
                  ? "CHAIN INTEGRITY VERIFIED: 100% UNCOMPROMISED"
                  : "CHAIN INTEGRITY ALERT: TAMPERING DETECTED"}
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Verified {verification.chain_length} cryptographic blocks · Broken at Block: {verification.broken_at_record_id ?? "NONE"}
              </p>
            </div>
          </div>
          <span className="px-2.5 py-1 rounded bg-[#0b101e] border border-slate-700 text-slate-200">
            ALGORITHM: SHA-256
          </span>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Total Blocks</span>
          <p className="text-2xl font-bold font-mono text-cyan-400 mt-2">
            {stats?.total_records ?? records.length}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Sealed immutable records</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Chain Status</span>
          <p className="text-2xl font-bold font-mono text-emerald-400 mt-2">
            ACTIVE
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Cryptographic integrity check</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Genesis Hash</span>
          <p className="text-xs font-bold font-mono text-slate-200 mt-3 truncate font-mono-tabular">
            {stats?.genesis_hash ? `${stats.genesis_hash.slice(0, 16)}...` : "GENESIS_ROOT"}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Root anchor block</p>
        </div>

        <div className="defense-card p-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Latest Sealed Block</span>
          <p className="text-xs font-bold font-mono text-slate-200 mt-3 truncate font-mono-tabular">
            {stats?.last_hash ? `${stats.last_hash.slice(0, 16)}...` : "Active Sync"}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Head of ledger</p>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="defense-card overflow-hidden">
        <div className="p-4 border-b border-[#1a233a] flex items-center justify-between">
          <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-white">
            Cryptographic Block Ledger
          </h2>
          <span className="text-[11px] font-mono text-slate-400">
            Showing last {records.length} chained entries
          </span>
        </div>

        {records.length === 0 ? (
          <div className="p-16 text-center text-slate-400 space-y-2">
            <div className="w-12 h-12 rounded-full bg-[#10172c] border border-slate-800 flex items-center justify-center mx-auto text-cyan-400">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <p className="text-sm font-bold text-white">Ledger Active & Ready</p>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              As alerts and detection events arrive from Edge AI, their SHA-256 hashes will be permanently chained here.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-[#0a0f1e] text-slate-400 border-b border-[#1a233a] uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="py-3 px-4">BLOCK ID</th>
                  <th className="py-3 px-4">EVENT REF</th>
                  <th className="py-3 px-4">SHA-256 HASH RECORD</th>
                  <th className="py-3 px-4">PREVIOUS BLOCK HASH</th>
                  <th className="py-3 px-4 text-right">TIMESTAMP (UTC)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1a233a]">
                {records.map((r) => (
                  <tr key={r.id} className="hover:bg-[#0f162b] transition-colors">
                    <td className="py-3 px-4 font-bold text-cyan-400">#{r.id}</td>
                    <td className="py-3 px-4 text-slate-300">
                      {r.event_id ? `Event #${r.event_id}` : "System Hash"}
                    </td>
                    <td className="py-3 px-4">
                      <span className="text-slate-200 bg-[#090d18] px-2 py-0.5 rounded border border-[#1a233a] text-[11px] font-mono-tabular">
                        {r.record_hash}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className="text-slate-400 text-[11px] font-mono-tabular">
                        {r.prev_hash ? `${r.prev_hash.slice(0, 20)}...` : "GENESIS_ROOT"}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right text-slate-400 font-mono-tabular">
                      {r.created_at ? new Date(r.created_at).toUTCString().slice(17, 25) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
