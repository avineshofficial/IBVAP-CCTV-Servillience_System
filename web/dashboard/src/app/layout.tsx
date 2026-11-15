"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { switchDemoRole } from "@/lib/api";
import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [currentTime, setCurrentTime] = useState<string>("");
  const [currentUtc, setCurrentUtc] = useState<string>("");
  const [currentRole, setCurrentRole] = useState<string>("admin");
  const [roleMenuOpen, setRoleMenuOpen] = useState(false);

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setCurrentTime(now.toLocaleTimeString("en-GB", { hour12: false }));
      setCurrentUtc(now.toISOString().slice(11, 19) + " ZULU");
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleRoleChange = async (role: "admin" | "post_commander" | "field_officer" | "hq_analyst") => {
    try {
      await switchDemoRole(role);
      setCurrentRole(role);
      setRoleMenuOpen(false);
      window.location.reload();
    } catch (e) {
      console.error("Role switch failed:", e);
    }
  };

  const navItems = [
    {
      href: "/",
      label: "Live Operations",
      sub: "Active Surveillance Grid",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      href: "/cameras",
      label: "Optical Sensors",
      sub: "Camera Grid & Streams",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
        </svg>
      ),
    },
    {
      href: "/alerts",
      label: "Incident Triage",
      sub: "Alerts & Breach Video",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      ),
    },
    {
      href: "/watchlist",
      label: "Threat Watchlist",
      sub: "Targets & POI Registry",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="12" r="3" strokeWidth={1.7} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg>
      ),
    },
    {
      href: "/audit",
      label: "Audit Ledger",
      sub: "Cryptographic SHA-256",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
      ),
    },
    {
      href: "/analytics",
      label: "Intelligence",
      sub: "Metrics & Reports",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
    },
    {
      href: "/security",
      label: "Security & RBAC",
      sub: "Zero-Trust & Compliance",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
      ),
    },
  ];

  return (
    <html lang="en" className="dark">
      <head>
        <title>IBVAP — Tactical Video Surveillance Platform</title>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased min-h-screen bg-[#050811] text-slate-100 flex flex-col selection:bg-cyan-500/30 selection:text-cyan-200">
        <div className="flex flex-1 min-h-screen">
          {/* Tactical Command Sidebar */}
          <aside className="w-60 fixed left-0 top-0 bottom-0 z-50 flex flex-col bg-[#070b16] border-r border-[#162035] shadow-[4px_0_24px_rgba(0,0,0,0.6)]">
            {/* Tactical C2 Crest Header */}
            <div className="p-4 border-b border-[#162035] bg-[#090e1d]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded bg-[#0a1122] border border-cyan-500/40 flex items-center justify-center shrink-0 shadow-[0_0_12px_rgba(0,229,255,0.15)]">
                  <svg className="w-4 h-4 text-cyan-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="8" strokeOpacity="0.7" />
                    <line x1="12" y1="2" x2="12" y2="6" />
                    <line x1="12" y1="18" x2="12" y2="22" />
                    <line x1="2" y1="12" x2="6" y2="12" />
                    <line x1="18" y1="12" x2="22" y2="12" />
                    <circle cx="12" cy="12" r="2" fill="#00e5ff" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-extrabold text-sm tracking-wider text-white uppercase">IBVAP</span>
                    <span className="text-[9px] font-mono px-1 py-0.2 bg-cyan-950/80 text-cyan-300 rounded-[2px] border border-cyan-800/60 font-semibold">
                      C4ISR
                    </span>
                  </div>
                  <p className="text-[9px] font-mono uppercase tracking-wider text-slate-400 truncate mt-0.5">
                    Defense Surveillance
                  </p>
                </div>
              </div>
            </div>

            {/* Navigation Menu */}
            <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
              <div className="px-2 py-1.5 text-[9px] font-mono font-bold uppercase tracking-widest text-slate-400">
                Command Panels
              </div>
              {navItems.map((item) => {
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-2.5 px-2.5 py-2 rounded-[4px] transition-all relative ${
                      isActive
                        ? "bg-[#0f172a] text-cyan-300 border-l-2 border-cyan-400 font-semibold shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                        : "text-slate-400 hover:text-slate-200 hover:bg-[#0b1120]"
                    }`}
                  >
                    <div className={`${isActive ? "text-cyan-400" : "text-slate-400"} shrink-0`}>
                      {item.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs tracking-wide truncate">{item.label}</p>
                      <p className="text-[9px] font-mono text-slate-400 truncate">{item.sub}</p>
                    </div>
                    {isActive && (
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#00e5ff] shrink-0"></span>
                    )}
                  </Link>
                );
              })}
            </nav>

            {/* Tactical Edge Node Telemetry Widget */}
            <div className="p-3 border-t border-[#162035] bg-[#050811]">
              <div className="rounded-[4px] p-2.5 border border-[#162035] bg-[#090e1b] space-y-2">
                <div className="flex items-center justify-between text-[11px] font-mono">
                  <span className="text-slate-400 text-[10px] tracking-wider uppercase font-semibold">EDGE PIPELINE</span>
                  <span className="flex items-center gap-1.5 text-emerald-400 text-[10px] font-bold">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse"></span>
                    SYNCED
                  </span>
                </div>
                <div className="space-y-1 text-[9px] font-mono text-slate-400 border-t border-[#162035] pt-1.5">
                  <div className="flex items-center justify-between">
                    <span>OUTPOST:</span>
                    <span className="text-slate-300 font-bold">BOP ALPHA</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>SENSOR:</span>
                    <span className="text-cyan-400 font-bold">CAM-01 ACTIVE</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>MODEL:</span>
                    <span className="text-slate-300">YOLOv11n (ONNX)</span>
                  </div>
                </div>
              </div>
            </div>
          </aside>

          {/* Main Console Viewport */}
          <div className="flex-1 ml-60 flex flex-col min-w-0">
            {/* Top Telemetry Header */}
            <header className="h-13 sticky top-0 z-40 bg-[#080d1a]/95 backdrop-blur-md border-b border-[#162035] px-6 flex items-center justify-between gap-4">
              {/* Left Telemetry Cluster */}
              <div className="flex items-center gap-2.5">
                <div className="flex items-center gap-2 px-2.5 py-1 rounded-[4px] bg-[#0c1324] border border-[#162035] text-[11px] font-mono">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse"></span>
                  <span className="text-slate-400">CORE SYSTEM:</span>
                  <span className="text-emerald-400 font-bold">ONLINE</span>
                </div>

                <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-[4px] bg-[#0c1324] border border-[#162035] text-[11px] font-mono">
                  <span className="text-slate-400">SECTOR:</span>
                  <span className="text-cyan-400 font-bold tracking-wide">SSB BOP-01 (IN-NPL BORDER)</span>
                </div>

                <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-[4px] bg-[#0c1324] border border-[#162035] text-[11px] font-mono">
                  <span className="text-slate-400">V-FENCE:</span>
                  <span className="text-amber-400 font-bold">ARMED</span>
                </div>
              </div>

              {/* Right Operational Controls & Military Clock */}
              <div className="flex items-center gap-4">
                {/* Real-time Military Clock */}
                <div className="text-right hidden md:block font-mono" suppressHydrationWarning>
                  <p className="text-xs font-bold text-slate-100 tracking-wider font-mono-tabular" suppressHydrationWarning>
                    {currentTime || "00:00:00"}
                  </p>
                  <p className="text-[10px] text-cyan-400/90 font-mono-tabular tracking-wider" suppressHydrationWarning>
                    {currentUtc || "00:00:00 ZULU"}
                  </p>
                </div>

                {/* Role Switcher */}
                <div className="relative">
                  <button
                    onClick={() => setRoleMenuOpen(!roleMenuOpen)}
                    className="flex items-center gap-2 px-2.5 py-1 rounded-[4px] bg-[#0e1629] border border-cyan-500/30 text-xs font-mono text-slate-200 hover:border-cyan-400 hover:bg-[#121c35] transition-all cursor-pointer"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                    <span className="uppercase font-bold text-cyan-300 tracking-wider text-[11px]">
                      {currentRole.replace("_", " ")}
                    </span>
                    <svg className="w-3 h-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Role Dropdown */}
                  {roleMenuOpen && (
                    <div className="absolute right-0 mt-1.5 w-52 rounded-[4px] bg-[#0c1324] border border-[#1e2e4f] shadow-2xl p-1 z-50">
                      <div className="px-2.5 py-1.5 text-[9px] font-mono uppercase tracking-wider text-slate-400 border-b border-[#162035]">
                        Security Clearance Level
                      </div>
                      {[
                        { id: "admin" as const, label: "Admin (HQ Full Access)" },
                        { id: "post_commander" as const, label: "Post Commander (BOP)" },
                        { id: "field_officer" as const, label: "Field Officer (Patrol)" },
                        { id: "hq_analyst" as const, label: "HQ Analyst (Read Only)" },
                      ].map((r) => (
                        <button
                          key={r.id}
                          onClick={() => handleRoleChange(r.id)}
                          className={`w-full text-left px-2.5 py-1.5 text-xs rounded-[3px] transition-colors flex items-center justify-between font-mono ${
                            currentRole === r.id
                              ? "bg-cyan-500/15 text-cyan-300 font-bold"
                              : "text-slate-300 hover:bg-[#131d36]"
                          }`}
                        >
                          <span className="text-[11px]">{r.label}</span>
                          {currentRole === r.id && <span className="text-cyan-400 text-xs">✓</span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </header>

            {/* Page Body Viewport */}
            <main className="p-5 flex-1 min-w-0">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
