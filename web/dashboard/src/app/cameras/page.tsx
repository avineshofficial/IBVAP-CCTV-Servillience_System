"use client";
import { useEffect, useState } from "react";
import { getCameras, getZones } from "@/lib/api";
import type { Camera, Zone } from "@/lib/api";

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [zones, setZones] = useState<Zone[]>([]);

  useEffect(() => {
    loadCameras();
    const interval = setInterval(loadCameras, 5000);
    return () => clearInterval(interval);
  }, []);

  async function loadCameras() {
    try {
      const [c, z] = await Promise.all([getCameras(), getZones()]);
      setCameras(c);
      setZones(z);
    } catch (e) { console.error(e); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">📹 Camera Management</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            {cameras.length} cameras registered · {cameras.filter(c => c.status === "online").length} online
          </p>
        </div>
      </div>

      {/* Camera Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 mb-8">
        {cameras.map((cam) => (
          <div key={cam.id} className="glass-card overflow-hidden">
            {/* Camera Preview (placeholder) */}
            <div
              className="h-44 flex items-center justify-center relative"
              style={{
                background: cam.status === "online"
                  ? "linear-gradient(135deg, #1a2332, #0d1421)"
                  : "linear-gradient(135deg, #2d1a1a, #1a0d0d)",
              }}
            >
              <div className="text-center">
                <p className="text-5xl mb-2">{cam.status === "online" ? "📹" : "📵"}</p>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {cam.status === "online" ? "Live Feed Available" : "Camera Offline"}
                </p>
              </div>
              {/* Status indicator */}
              <div className="absolute top-3 right-3">
                <span
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded-full"
                  style={{
                    background: cam.status === "online" ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)",
                    color: cam.status === "online" ? "var(--accent-green)" : "var(--accent-red)",
                    border: `1px solid ${cam.status === "online" ? "rgba(16,185,129,0.4)" : "rgba(239,68,68,0.4)"}`,
                  }}
                >
                  <span className={`status-dot ${cam.status === "online" ? "status-online" : "status-offline"}`}></span>
                  {cam.status}
                </span>
              </div>
              {/* PTZ badge */}
              {cam.is_ptz && (
                <div className="absolute top-3 left-3">
                  <span className="badge badge-medium">PTZ</span>
                </div>
              )}
            </div>

            {/* Info */}
            <div className="p-4">
              <h3 className="text-sm font-semibold mb-2">{cam.name}</h3>
              <div className="space-y-1">
                <InfoRow label="UID" value={cam.camera_uid} />
                <InfoRow label="BOP" value={cam.bop_id} />
                <InfoRow label="Location" value={
                  cam.lat && cam.lng ? `${cam.lat.toFixed(4)}, ${cam.lng.toFixed(4)}` : "Not set"
                } />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Virtual Fence Zones */}
      <div className="glass-card p-5">
        <h2 className="text-lg font-semibold mb-4">🔒 Virtual Fence Zones</h2>
        {zones.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No zones defined. Zones are created automatically when the edge pipeline starts.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {zones.map((zone) => (
              <div
                key={zone.id}
                className="p-4 rounded-lg"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border-subtle)" }}
              >
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium">{zone.name}</h3>
                  <span className={`badge ${zone.is_active ? "badge-medium" : "badge-low"}`}>
                    {zone.rule_type}
                  </span>
                </div>
                <InfoRow label="Camera" value={zone.camera_uid} />
                <InfoRow label="Points" value={`${zone.polygon_points_pixel.length} vertices`} />
                <InfoRow label="Active" value={zone.is_active ? "Yes" : "No"} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs">
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
