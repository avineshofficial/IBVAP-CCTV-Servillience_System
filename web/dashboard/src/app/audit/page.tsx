"use client";
import { useEffect, useState } from "react";
import { getAuditChain, verifyFullChain, getAuditStats, demoTamper } from "@/lib/api";
import type { AuditRecord, ChainVerification, AuditStats } from "@/lib/api";

export default function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [verification, setVerification] = useState<ChainVerification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [tampering, setTampering] = useState(false);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 4000);
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [r, s] = await Promise.all([getAuditChain(), getAuditStats()]);
      setRecords(r);
      setStats(s);
    } catch (e) { console.error(e); }
  }

  async function handleVerify() {
    setVerifying(true);
    setVerification(null);
    try {
      const result = await verifyFullChain();
      setVerification(result);
    } catch (e) { console.error(e); }
    setVerifying(false);
  }

  async function handleTamper() {
    if (records.length === 0) return;
    setTampering(true);
    try {
      const targetId = records[Math.floor(records.length / 2)]?.id || records[0]?.id;
      await demoTamper(targetId);
      alert(`Record #${targetId} tampered! Now click "Verify Chain" to detect it.`);
      await loadData();
    } catch (e) { console.error(e); }
    setTampering(false);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">🔗 Tamper-Evident Audit Trail</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            SHA-256 hash-chain ledger · Every record is chained — tampering is detectable
          </p>
        </div>
        <div className="flex gap-3">
          <button className="btn btn-primary" onClick={handleVerify} disabled={verifying}>
            {verifying ? "⏳ Verifying..." : "🔍 Verify Chain"}
          </button>
          <button className="btn btn-danger" onClick={handleTamper} disabled={tampering || records.length === 0}>
            {tampering ? "⏳ Tampering..." : "💥 Demo Tamper"}
          </button>
        </div>
      </div>

      {/* Verification Result */}
      {verification && (
        <div
          className="glass-card p-5 mb-6"
          style={{
            borderColor: verification.verified ? "var(--accent-green)" : "var(--accent-red)",
            boxShadow: verification.verified
              ? "0 0 20px var(--glow-green)"
              : "0 0 20px var(--glow-red)",
          }}
        >
          <div className="flex items-center gap-4">
            <span className="text-4xl">{verification.verified ? "✅" : "❌"}</span>
            <div>
              <h3 className="text-lg font-bold" style={{
                color: verification.verified ? "var(--accent-green)" : "var(--accent-red)"
              }}>
                {verification.verified ? "CHAIN INTEGRITY VERIFIED" : "⚠️ CHAIN BROKEN — TAMPERING DETECTED"}
              </h3>
              <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                {verification.message}
              </p>
              <div className="flex gap-4 mt-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                <span>Chain length: {verification.chain_length}</span>
                {verification.verified_count !== undefined && (
                  <span>Verified: {verification.verified_count}</span>
                )}
                {verification.broken_at_record_id && (
                  <span style={{ color: "var(--accent-red)" }}>
                    Broken at record #{verification.broken_at_record_id}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="stat-card">
          <p className="text-3xl font-bold" style={{ color: "var(--accent-blue)" }}>
            {stats?.total_records ?? 0}
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>Total Records</p>
        </div>
        <div className="stat-card">
          <p className="text-xs font-mono truncate" style={{ color: "var(--accent-cyan)" }}>
            {stats?.last_hash?.slice(0, 32) ?? "—"}...
          </p>
          <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>Last Hash</p>
        </div>
        <div className="stat-card">
          <p className="text-xs font-mono truncate" style={{ color: "var(--accent-purple)" }}>
            {stats?.genesis_hash?.slice(0, 32) ?? "—"}...
          </p>
          <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>Genesis Hash</p>
        </div>
      </div>

      {/* Hash Chain Visualization */}
      <div className="glass-card p-5">
        <h2 className="text-lg font-semibold mb-4">Hash Chain Records</h2>
        {records.length === 0 ? (
          <div className="text-center py-8" style={{ color: "var(--text-secondary)" }}>
            <p className="text-4xl mb-2">🔗</p>
            <p>No audit records yet</p>
            <p className="text-xs mt-1">Records are created when alerts are generated through the pipeline</p>
          </div>
        ) : (
          <div className="space-y-3">
            {records.map((record, idx) => (
              <div key={record.id} className="flex items-start gap-4">
                {/* Chain visualization */}
                <div className="flex flex-col items-center" style={{ minWidth: "24px" }}>
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                    style={{ background: "var(--accent-blue)", color: "white" }}
                  >
                    {record.id}
                  </div>
                  {idx < records.length - 1 && (
                    <div className="w-px h-8 mt-1" style={{ background: "var(--border-subtle)" }} />
                  )}
                </div>

                {/* Record details */}
                <div
                  className="flex-1 p-3 rounded-lg"
                  style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)" }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium">Record #{record.id}</span>
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      {new Date(record.timestamp * 1000).toLocaleString()}
                    </span>
                  </div>
                  <div className="space-y-1">
                    <div className="flex gap-2 text-xs">
                      <span style={{ color: "var(--text-secondary)" }}>Hash:</span>
                      <span className="font-mono" style={{ color: "var(--accent-cyan)" }}>
                        {record.record_hash.slice(0, 40)}...
                      </span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span style={{ color: "var(--text-secondary)" }}>Prev:</span>
                      <span className="font-mono" style={{ color: "var(--accent-purple)" }}>
                        {record.prev_hash.slice(0, 40)}...
                      </span>
                    </div>
                    {record.signer && (
                      <div className="flex gap-2 text-xs">
                        <span style={{ color: "var(--text-secondary)" }}>Signer:</span>
                        <span>{record.signer}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
