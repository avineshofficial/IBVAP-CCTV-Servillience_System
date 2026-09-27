import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IBVAP — Intelligent Border Video Analytics Platform",
  description: "AI-powered border surveillance dashboard for real-time detection, alerts, and tamper-evident audit trail",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased" style={{ fontFamily: "'Inter', sans-serif" }}>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 ml-64 p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}

function Sidebar() {
  const navItems = [
    { href: "/", icon: "📊", label: "Dashboard", id: "nav-dashboard" },
    { href: "/alerts", icon: "🚨", label: "Alerts", id: "nav-alerts" },
    { href: "/cameras", icon: "📹", label: "Cameras", id: "nav-cameras" },
    { href: "/audit", icon: "🔗", label: "Audit Trail", id: "nav-audit" },
    { href: "/watchlist", icon: "👁", label: "Watchlist", id: "nav-watchlist" },
    { href: "/analytics", icon: "📈", label: "Analytics", id: "nav-analytics" },
    { href: "/security", icon: "🛡️", label: "Security System", id: "nav-security" },
  ];

  return (
    <aside
      className="fixed left-0 top-0 h-full w-64 flex flex-col"
      style={{
        background: "linear-gradient(180deg, #0d1117 0%, #0a0e1a 100%)",
        borderRight: "1px solid var(--border-subtle)",
        zIndex: 50,
      }}
    >
      {/* Logo */}
      <div className="p-6 pb-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold"
            style={{
              background: "linear-gradient(135deg, #3b82f6, #06b6d4)",
              color: "white",
            }}
          >
            IB
          </div>
          <div>
            <h1 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
              IBVAP
            </h1>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Border Analytics
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => (
          <a key={item.id} href={item.href} className="sidebar-link" id={item.id}>
            <span className="text-lg">{item.icon}</span>
            <span>{item.label}</span>
          </a>
        ))}
      </nav>

      {/* System Status */}
      <div className="p-4" style={{ borderTop: "1px solid var(--border-subtle)" }}>
        <div className="glass-card p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="status-dot status-online"></span>
            <span className="text-xs font-medium" style={{ color: "var(--accent-green)" }}>
              System Online
            </span>
          </div>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            SIH 2026 · PS 26187
          </p>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            SSB · Ministry of Home Affairs
          </p>
        </div>
      </div>
    </aside>
  );
}
