"use client";
import React, { useEffect, useState, useCallback } from "react";
import { getWatchlist, addWatchlistEntry } from "@/lib/api";
import type { WatchlistEntry } from "@/lib/api";

export default function WatchlistPage() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    entry_type: "face",
    reference_data: "",
    label: "",
    category: "suspect",
    source_agency: "SSB-INTEL",
  });

  const loadWatchlist = useCallback(async () => {
    try {
      const data = await getWatchlist();
      setEntries(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Watchlist load failed:", e);
    }
  }, []);

  useEffect(() => {
    let isSubscribed = true;
    async function fetchWatchlist() {
      try {
        const data = await getWatchlist();
        if (isSubscribed) {
          setEntries(Array.isArray(data) ? data : []);
        }
      } catch (e) {
        console.error("Watchlist load failed:", e);
      }
    }
    fetchWatchlist();
    return () => {
      isSubscribed = false;
    };
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!form.label || !form.reference_data) return;
    try {
      await addWatchlistEntry(form);
      setShowAdd(false);
      setForm({
        entry_type: "face",
        reference_data: "",
        label: "",
        category: "suspect",
        source_agency: "SSB-INTEL",
      });
      await loadWatchlist();
    } catch (err) {
      console.error("Add watchlist error:", err);
    }
  }

  const categoryBadges: Record<string, string> = {
    suspect: "badge-critical",
    poi: "badge-high",
    bolo: "badge-medium",
    high_threat: "badge-critical",
  };

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      {/* Tactical Watchlist Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#162035] pb-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_6px_#00e5ff]"></span>
            <h1 className="text-sm font-bold uppercase tracking-widest text-slate-100 font-mono">
              TARGET & THREAT WATCHLIST
            </h1>
            <span className="badge-status badge-online">
              <span className="status-pip status-pip-online"></span> {entries.length} TARGETS LOADED
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-mono mt-0.5">
            Facial recognition embeddings & ANPR license plate registry · Automated real-time optical matching
          </p>
        </div>

        <button
          onClick={() => setShowAdd(!showAdd)}
          className="btn-tactical-primary text-xs font-mono uppercase tracking-wider"
        >
          {showAdd ? "✕ Cancel" : "+ Register Target"}
        </button>
      </div>

      {/* Add Target Drawer */}
      {showAdd && (
        <div className="tactical-panel p-4 space-y-3.5">
          <div className="flex items-center justify-between border-b border-[#162035] pb-2.5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-100 font-mono flex items-center gap-2">
              <span className="text-cyan-400">🎯</span> Add New Watchlist Entry
            </h2>
            <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-800/40">
              HMAC-SHA256 SECURED
            </span>
          </div>

          <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-2 gap-3.5 text-xs font-mono">
            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">TARGET TYPE</label>
              <select
                value={form.entry_type}
                onChange={(e) => setForm({ ...form, entry_type: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs cursor-pointer"
              >
                <option value="face">Facial Biometric Embedding</option>
                <option value="plate">ANPR Vehicle License Plate</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">TARGET LABEL / IDENTITY</label>
              <input
                type="text"
                required
                placeholder="e.g. Suspect Alpha or DL-1CAB-1234"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">THREAT CATEGORY</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs cursor-pointer"
              >
                <option value="suspect">Suspect / Fugitive</option>
                <option value="poi">Person of Interest (POI)</option>
                <option value="bolo">Be On the Lookout (BOLO)</option>
                <option value="high_threat">High Priority Threat</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-400 mb-1 text-[11px]">SOURCE AGENCY / OUTPOST</label>
              <input
                type="text"
                placeholder="e.g. SSB-HQ / MHA-INTEL"
                value={form.source_agency}
                onChange={(e) => setForm({ ...form, source_agency: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-slate-400 mb-1 text-[11px]">REFERENCE BIOMETRIC / PLATE STRING</label>
              <input
                type="text"
                required
                placeholder="License Plate string (e.g. UP32AB1234) or Biometric Vector ID"
                value={form.reference_data}
                onChange={(e) => setForm({ ...form, reference_data: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none font-mono text-xs"
              />
            </div>

            <div className="md:col-span-2 flex justify-end gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                className="btn-tactical-outline text-xs"
              >
                Cancel
              </button>
              <button type="submit" className="btn-tactical-primary text-xs">
                Seal & Register to Watchlist
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Target Registry Table */}
      <div className="tactical-panel overflow-hidden">
        <div className="p-3 border-b border-[#162035] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-slate-100">
              Active Target Registry
            </h2>
          </div>
          <span className="text-[10px] font-mono text-slate-400 font-mono-tabular">
            TOTAL TARGETS: {entries.length}
          </span>
        </div>

        {entries.length === 0 ? (
          <div className="p-14 text-center text-slate-400 space-y-2.5">
            <div className="w-10 h-10 rounded-[4px] bg-[#090e1b] border border-[#162035] flex items-center justify-center mx-auto text-cyan-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <circle cx="12" cy="12" r="7" strokeDasharray="3 3" />
                <circle cx="12" cy="12" r="2" fill="#00e5ff" />
              </svg>
            </div>
            <p className="text-sm font-bold text-slate-100 font-mono uppercase tracking-wider">
              No Watchlist Targets Configured
            </p>
            <p className="text-[11px] text-slate-400 max-w-sm mx-auto font-mono leading-relaxed">
              Register wanted persons or suspicious vehicle plates above. The edge AI engine compares detected faces and vehicles against this registry in real time.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-[#070b16] text-slate-400 border-b border-[#162035] uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="py-2.5 px-3.5">TARGET UID</th>
                  <th className="py-2.5 px-3.5">MODALITY</th>
                  <th className="py-2.5 px-3.5">TARGET IDENTITY</th>
                  <th className="py-2.5 px-3.5">THREAT CATEGORY</th>
                  <th className="py-2.5 px-3.5">INTELLIGENCE AGENCY</th>
                  <th className="py-2.5 px-3.5 text-right">DATE REGISTERED</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#162035]">
                {entries.map((item) => (
                  <tr key={item.id} className="hover:bg-[#0c1324] transition-colors">
                    <td className="py-2.5 px-3.5 font-bold text-cyan-400 font-mono-tabular">
                      #{item.id}
                    </td>
                    <td className="py-2.5 px-3.5 uppercase text-slate-300 font-semibold text-[11px]">
                      {item.entry_type === "face" ? "👤 BIOMETRIC FACE" : "🚗 ANPR PLATE"}
                    </td>
                    <td className="py-2.5 px-3.5 font-bold text-white">
                      {item.label}
                    </td>
                    <td className="py-2.5 px-3.5">
                      <span className={`badge-status ${categoryBadges[item.category || "suspect"] || "badge-medium"}`}>
                        {(item.category || "suspect").replace("_", " ")}
                      </span>
                    </td>
                    <td className="py-2.5 px-3.5 text-slate-400">
                      {item.source_agency || "SSB-INTEL"}
                    </td>
                    <td className="py-2.5 px-3.5 text-right text-slate-400 font-mono-tabular">
                      {item.added_at ? new Date(item.added_at).toLocaleDateString("en-GB") : "—"}
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
