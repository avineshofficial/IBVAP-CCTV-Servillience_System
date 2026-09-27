/**
 * IBVAP Dashboard — API Client
 * ==============================
 * Every page in this app imports from here. This file talks to the
 * Core Platform FastAPI backend (core/main.py) — see that project's
 * README for how to start it (`python -m core.main`, default
 * http://localhost:8000).
 *
 * Set NEXT_PUBLIC_API_URL in web/dashboard/.env.local to point at a
 * different core host (e.g. an edge box on the LAN during a demo).
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

const WS_BASE = API_BASE.replace(/^http/, "ws");

// ─────────────────────────────────────────────
// Shared fetch helper
// ─────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${options.method || "GET"} ${path} → HTTP ${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function qs(params?: Record<string, string | number | undefined>): string {
  if (!params) return "";
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries as [string, string][]).toString();
}

// ─────────────────────────────────────────────
// Types — mirror core/schemas.py exactly
// ─────────────────────────────────────────────

export interface Camera {
  id: number;
  name: string;
  camera_uid: string;
  bop_id: string;
  lat?: number | null;
  lng?: number | null;
  rtsp_url?: string | null;
  is_ptz: boolean;
  status: string;
  created_at?: string | null;
}

export interface Zone {
  id: number;
  zone_uid: string;
  name: string;
  camera_uid: string;
  polygon_points_pixel: number[][];
  rule_type: "line_cross" | "dwell" | "direction" | "exclusion";
  dwell_threshold?: number | null;
  direction_vector?: number[] | null;
  polygon_points_geo?: number[][] | null;
  is_active: boolean;
  created_at?: string | null;
}

export interface Alert {
  id: number;
  severity: "low" | "medium" | "high" | "critical";
  alert_type: string;
  message?: string | null;
  data_json?: Record<string, unknown> | null;
  status: "new" | "acknowledged" | "resolved" | "false_positive";
  created_at?: string | null;
  resolved_at?: string | null;
  notes?: string | null;
}

export interface DetectionEvent {
  id: number;
  camera_uid: string;
  track_id?: number | null;
  event_type: string;
  confidence?: number | null;
  timestamp: number;
  metadata_json?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface AuditRecord {
  id: number;
  event_id?: number | null;
  record_hash: string;
  prev_hash: string;
  timestamp: number;
  signer?: string | null;
  created_at?: string | null;
}

export interface ChainVerification {
  verified: boolean;
  chain_length: number;
  verified_count?: number;
  message: string;
  last_hash?: string;
}

export interface AuditStats {
  total_records: number;
  last_hash: string;
  last_timestamp: number | null;
  genesis_hash: string;
}

export interface WatchlistEntry {
  id: number;
  entry_type: "face" | "plate";
  label?: string | null;
  category?: string | null;
  source_agency?: string | null;
  reference_hash: string;
  is_active: boolean;
  added_at?: string | null;
}

export interface DashboardStats {
  total_cameras: number;
  cameras_online: number;
  total_events: number;
  total_alerts: number;
  active_alerts: number;
  critical_alerts: number;
  total_tracks: number;
  fence_breaches: number;
  system_uptime: number;
}

export interface SecurityStats {
  security_score: number;
  security_status: string;
  active_sessions: number;
  total_users: number;
  failed_logins_24h: number;
  crypto_chain_verified: boolean;
  edge_mutual_auth: boolean;
  dpdp_compliance_status: string;
  last_key_rotation: string;
  encryption_algorithm: string;
  model_signing_active: boolean;
}

export interface SecurityLogItem {
  id: number;
  event_type: string;
  severity: string;
  actor: string;
  ip_address?: string | null;
  details?: string | null;
  timestamp: string;
}

export interface RolePermission {
  role: string;
  role_name: string;
  level: number;
  permissions: string[];
}

export interface DPDPCheckItem {
  category: string;
  requirement: string;
  status: string;
  details: string;
}

export interface DPDPCompliance {
  overall_compliance: string;
  audit_date: string;
  checklist: DPDPCheckItem[];
  salted_hashing_active: boolean;
  privacy_blur_default: boolean;
  purpose_limited_retention_days: number;
}

// ─────────────────────────────────────────────
// Dashboard stats
// ─────────────────────────────────────────────

export const getStats = () => apiFetch<DashboardStats>("/api/v1/stats");

// ─────────────────────────────────────────────
// Cameras
// ─────────────────────────────────────────────

export const getCameras = () => apiFetch<Camera[]>("/api/v1/cameras");

export const createCamera = (data: Partial<Camera>) =>
  apiFetch<Camera>("/api/v1/cameras", { method: "POST", body: JSON.stringify(data) });

// ─────────────────────────────────────────────
// Alerts
// ─────────────────────────────────────────────

export const getAlerts = (params?: {
  status?: string;
  severity?: string;
  alert_type?: string;
  limit?: string | number;
  offset?: string | number;
}) => apiFetch<Alert[]>(`/api/v1/alerts${qs(params)}`);

export const updateAlert = (
  id: number,
  data: { status?: string; notes?: string; assigned_to?: number }
) => apiFetch<Alert>(`/api/v1/alerts/${id}`, { method: "PATCH", body: JSON.stringify(data) });

// ─────────────────────────────────────────────
// Events
// ─────────────────────────────────────────────

export const getEvents = (params?: {
  event_type?: string;
  camera_uid?: string;
  limit?: string | number;
  offset?: string | number;
}) => apiFetch<DetectionEvent[]>(`/api/v1/events${qs(params)}`);

// ─────────────────────────────────────────────
// Zones (virtual fences)
// ─────────────────────────────────────────────

export const getZones = () => apiFetch<Zone[]>("/api/v1/zones");

export const createZone = (data: Partial<Zone>) =>
  apiFetch<Zone>("/api/v1/zones", { method: "POST", body: JSON.stringify(data) });

// ─────────────────────────────────────────────
// Audit trail
// ─────────────────────────────────────────────

export const getAuditChain = (limit = 50) =>
  apiFetch<AuditRecord[]>(`/api/v1/audit/chain${qs({ limit })}`);

export const verifyFullChain = () =>
  apiFetch<ChainVerification>("/api/v1/audit/verify-all");

export const verifyEventChain = (eventId: number) =>
  apiFetch<ChainVerification>(`/api/v1/audit/${eventId}/verify`);

export const getAuditStats = () => apiFetch<AuditStats>("/api/v1/audit/stats");

export const demoTamper = (recordId: number) =>
  apiFetch<{ status: string; message: string }>(
    `/api/v1/audit/demo-tamper/${recordId}`,
    { method: "POST" }
  );

// ─────────────────────────────────────────────
// Watchlist
// ─────────────────────────────────────────────

export const getWatchlist = () => apiFetch<WatchlistEntry[]>("/api/v1/watchlist");

export const addWatchlistEntry = (data: {
  entry_type: string;
  reference_data: string;
  label?: string;
  category?: string;
  source_agency?: string;
}) =>
  apiFetch<WatchlistEntry>("/api/v1/watchlist", {
    method: "POST",
    body: JSON.stringify(data),
  });

// ─────────────────────────────────────────────
// Security
// ─────────────────────────────────────────────

export const getSecurityStats = () => apiFetch<SecurityStats>("/api/v1/security/stats");

export const getSecurityLogs = (params?: { limit?: string | number; severity?: string }) =>
  apiFetch<SecurityLogItem[]>(`/api/v1/security/logs${qs(params)}`);

export const getRBACMatrix = () => apiFetch<RolePermission[]>("/api/v1/security/rbac-matrix");

export const getDPDPCompliance = () =>
  apiFetch<DPDPCompliance>("/api/v1/security/dpdp-compliance");

export const rotateSecurityKeys = () =>
  apiFetch<{ status: string; message: string }>("/api/v1/security/rotate-keys", {
    method: "POST",
  });

export const runSecurityAuditScan = () =>
  apiFetch<{ status: string; message: string }>("/api/v1/security/run-audit", {
    method: "POST",
  });

// ─────────────────────────────────────────────
// WebSocket — live alert stream
// ─────────────────────────────────────────────

export function connectAlertWebSocket(
  onMessage: (data: Record<string, unknown>) => void
): WebSocket | null {
  if (typeof window === "undefined") return null;
  try {
    const ws = new WebSocket(`${WS_BASE}/ws/alerts`);
    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onerror = () => {
      /* loadAlerts()'s 3s poll covers us while the socket is down */
    };
    return ws;
  } catch {
    return null;
  }
}
