"use client";
import { useEffect, useState } from "react";
import { getWatchlist, addWatchlistEntry } from "@/lib/api";
import type { WatchlistEntry } from "@/lib/api";

export default function WatchlistPage() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    entry_type: "plate",
    reference_data: "",
    label: "",
    category: "suspect",
    source_agency: "",
  });

  useEffect(() => { loadWatchlist(); }, []);

  async function loadWatchlist() {
    try { setEntries(await getWatchlist()); }
    catch (e) { console.error(e); }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    try {
      await addWatchlistEntry(form);
      setShowAdd(false);
      setForm({ entry_type: "plate", reference_data: "", label: "", category: "suspect", source_agency: "" });
      loadWatchlist();
    } catch (err) { console.error(err); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">👁 Watchlist Management</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Face and plate watchlists · All queries are audit-logged
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "✕ Cancel" : "+ Add Entry"}
        </button>
      </div>

      {/* Add Form */}
      {showAdd && (
        <div className="glass-card p-5 mb-6">
          <h3 className="text-sm font-semibold mb-4">Add Watchlist Entry</h3>
          <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs mb-1 block" style={{ color: "var(--text-secondary)" }}>Type</label>
              <select
                value={form.entry_type}
                onChange={(e) => setForm({ ...form, entry_type: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              >
                <option value="plate">License Plate</option>
                <option value="face">Face</option>
              </select>
            </div>
            <div>
              <label className="text-xs mb-1 block" style={{ color: "var(--text-secondary)" }}>Category</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              >
                <option value="wanted">Wanted</option>
                <option value="suspect">Suspect</option>
                <option value="vip">VIP</option>
                <option value="stolen_vehicle">Stolen Vehicle</option>
              </select>
            </div>
            <div>
              <label className="text-xs mb-1 block" style={{ color: "var(--text-secondary)" }}>
                {form.entry_type === "plate" ? "Plate Number" : "Reference ID"}
              </label>
              <input
                type="text" required
                placeholder={form.entry_type === "plate" ? "MH12AB1234" : "Face reference ID"}
                value={form.reference_data}
                onChange={(e) => setForm({ ...form, reference_data: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="text-xs mb-1 block" style={{ color: "var(--text-secondary)" }}>Label</label>
              <input
                type="text"
                placeholder="Description or name"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="text-xs mb-1 block" style={{ color: "var(--text-secondary)" }}>Source Agency</label>
              <input
                type="text"
                placeholder="e.g., SSB, BSF, Police"
                value={form.source_agency}
                onChange={(e) => setForm({ ...form, source_agency: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
              />
            </div>
            <div className="flex items-end">
              <button type="submit" className="btn btn-primary w-full">Add to Watchlist</button>
            </div>
          </form>
        </div>
      )}

      {/* Watchlist Table */}
      <div className="glass-card overflow-hidden">
        {entries.length === 0 ? (
          <div className="p-12 text-center" style={{ color: "var(--text-secondary)" }}>
            <p className="text-4xl mb-3">👁</p>
            <p className="text-lg">Watchlist is empty</p>
            <p className="text-sm mt-1">Add face or plate entries to monitor</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Type</th>
                <th>Label</th>
                <th>Category</th>
                <th>Source</th>
                <th>Hash (Stored)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="font-mono text-xs">#{entry.id}</td>
                  <td>
                    <span className={`badge ${entry.entry_type === "face" ? "badge-high" : "badge-medium"}`}>
                      {entry.entry_type === "face" ? "👤 Face" : "🔢 Plate"}
                    </span>
                  </td>
                  <td className="text-sm">{entry.label || "—"}</td>
                  <td>
                    <span className="text-xs px-2 py-1 rounded" style={{
                      background: entry.category === "wanted" ? "rgba(239,68,68,0.15)" :
                        entry.category === "vip" ? "rgba(139,92,246,0.15)" : "rgba(245,158,11,0.15)",
                      color: entry.category === "wanted" ? "var(--accent-red)" :
                        entry.category === "vip" ? "var(--accent-purple)" : "var(--accent-amber)",
                    }}>
                      {entry.category || "—"}
                    </span>
                  </td>
                  <td className="text-xs">{entry.source_agency || "—"}</td>
                  <td className="font-mono text-xs" style={{ color: "var(--accent-cyan)" }}>
                    {entry.reference_hash.slice(0, 24)}...
                  </td>
                  <td>
                    <span className={`status-dot ${entry.is_active ? "status-online" : "status-offline"}`}></span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Privacy Notice */}
      <div className="mt-6 p-4 rounded-lg" style={{ background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)" }}>
        <p className="text-xs" style={{ color: "var(--accent-blue)" }}>
          🔒 <strong>DPDP Act Compliance:</strong> Plate numbers are stored as salted HMAC-SHA256 hashes, never in plaintext.
          All watchlist queries are audit-logged. Face embeddings are stored as encrypted vectors.
        </p>
      </div>
    </div>
  );
}
