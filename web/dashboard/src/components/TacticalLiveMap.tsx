"use client";
import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { updateAlert } from "@/lib/api";
import type { Camera, Alert } from "@/lib/api";

interface TacticalLiveMapProps {
  cameras: Camera[];
  alerts: Alert[];
  selectedCameraUid?: string;
  onSelectCamera?: (camera: Camera) => void;
  className?: string;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export default function TacticalLiveMap({
  cameras,
  alerts,
  selectedCameraUid = "cam_01",
  onSelectCamera,
  className = "",
  isExpanded = false,
  onToggleExpand,
}: TacticalLiveMapProps) {
  // Map display mode: dark tactical by default
  const [mapMode, setMapMode] = useState<"dark_tactical" | "satellite" | "roadmap">("dark_tactical");

  // Tactical zoom: default 15 for sector-level view
  const [zoomLevel, setZoomLevel] = useState<number>(15);

  // Real-time location state (continuous watchPosition)
  const [realTimeLocation, setRealTimeLocation] = useState<{
    lat: number;
    lng: number;
    accuracy?: number;
  } | null>(null);
  const [isLocating, setIsLocating] = useState<boolean>(false);
  const [locationSource, setLocationSource] = useState<"gps" | "sector">("sector");
  const [locationError, setLocationError] = useState<string | null>(null);
  const watchIdRef = useRef<number | null>(null);

  // Default sector base coordinates (Kalasalingam area)
  const defaultCenter = useMemo(() => ({ lat: 9.57435, lng: 77.67874 }), []);

  // Current active map center
  const [centerCoords, setCenterCoords] = useState<{ lat: number; lng: number }>(defaultCenter);
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);
  const [silencedAlertIds, setSilencedAlertIds] = useState<number[]>([]);

  // State-driven time ticker for pure rendering
  const [currentTime, setCurrentTime] = useState<number>(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(Date.now());
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // ─── Continuous GPS via watchPosition ───────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined" || !navigator.geolocation) {
      // locationSource defaults to "sector" from initial state — no setState needed
      return;
    }

    const id = navigator.geolocation.watchPosition(
      (position) => {
        const liveLat = position.coords.latitude;
        const liveLng = position.coords.longitude;
        const acc = Math.round(position.coords.accuracy);

        setRealTimeLocation({ lat: liveLat, lng: liveLng, accuracy: acc });
        setCenterCoords({ lat: liveLat, lng: liveLng });
        setLocationSource("gps");
        setIsLocating(false);
        setLocationError(null);
      },
      (err) => {
        console.warn("Geolocation watch error:", err.message);
        setLocationError("GPS unavailable. Using sector coordinates.");
        setLocationSource("sector");
        setIsLocating(false);
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 5000,
      }
    );

    watchIdRef.current = id;

    return () => {
      navigator.geolocation.clearWatch(id);
      watchIdRef.current = null;
    };
  }, []);

  // Manual re-acquire GPS
  const acquireRealTimeLocation = useCallback(() => {
    if (typeof window === "undefined" || !navigator.geolocation) {
      setLocationError("Geolocation not supported.");
      return;
    }
    setIsLocating(true);
    setLocationError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setRealTimeLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.round(pos.coords.accuracy) });
        setCenterCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocationSource("gps");
        setIsLocating(false);
      },
      (err) => {
        console.warn("GPS re-acquire error:", err.message);
        setLocationError("GPS permission denied or unavailable.");
        setIsLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 5000 }
    );
  }, []);

  // Parse alert timestamp safely
  const parseAlertTime = useCallback((createdStr?: string | null): number | null => {
    if (!createdStr) return null;
    let iso = createdStr;
    if (!iso.includes("T") && iso.includes(" ")) {
      iso = iso.replace(" ", "T");
    }
    if (!iso.endsWith("Z") && !iso.includes("+")) {
      iso += "Z";
    }
    const t = new Date(iso).getTime();
    return isNaN(t) ? null : t;
  }, []);

  // Check if a specific camera UID has an active fresh alert (within last 60 seconds and not silenced)
  const isCameraAlerting = useCallback(
    (cameraUid: string) => {
      return alerts.some((a) => {
        if (a.status !== "new") return false;
        if (silencedAlertIds.includes(a.id)) return false;

        const alertTime = parseAlertTime(a.created_at);
        if (alertTime !== null && currentTime - alertTime > 60 * 1000) return false;

        let dataJson: Record<string, unknown> | undefined;
        if (typeof a.data_json === "string") {
          try { dataJson = JSON.parse(a.data_json); } catch { dataJson = undefined; }
        } else if (a.data_json && typeof a.data_json === "object") {
          dataJson = a.data_json as Record<string, unknown>;
        }

        const targetUid = (dataJson?.camera_uid as string) || (dataJson?.camera_id as string) || (dataJson?.cam as string);
        if (targetUid && targetUid.toLowerCase() === cameraUid.toLowerCase()) return true;
        if (a.message && a.message.toLowerCase().includes(cameraUid.toLowerCase())) return true;

        return false;
      });
    },
    [alerts, silencedAlertIds, currentTime, parseAlertTime]
  );

  // Find the currently active alert
  const activeAlert = useMemo(() => {
    return alerts.find((a) => {
      if (a.status !== "new" || silencedAlertIds.includes(a.id)) return false;
      const alertTime = parseAlertTime(a.created_at);
      if (alertTime !== null && currentTime - alertTime > 60 * 1000) return false;
      return true;
    });
  }, [alerts, silencedAlertIds, currentTime, parseAlertTime]);

  // Handle immediate silence/acknowledge of alert
  const handleSilenceAlert = async () => {
    if (activeAlert) {
      setSilencedAlertIds((prev) => [...prev, activeAlert.id]);
      try {
        await updateAlert(activeAlert.id, { status: "acknowledged" });
      } catch (e) {
        console.warn("Acknowledge alert failed:", e);
      }
    }
  };

  // ONLY ACTIVE CAMERAS APPEAR
  const onlineCameras = cameras.filter((c) => c.status === "online");
  const displayCameras: Camera[] =
    onlineCameras.length > 0
      ? onlineCameras
      : [
          {
            id: 1,
            camera_uid: "cam_01",
            name: "Primary Optical Sensor (Lenovo 300 FHD Live)",
            status: "online",
            lat: centerCoords.lat,
            lng: centerCoords.lng,
            is_ptz: false,
            bop_id: "bop_alpha",
          },
        ];

  // Zoom controls
  const handleZoomIn = () => setZoomLevel((z) => Math.min(z + 1, 19));
  const handleZoomOut = () => setZoomLevel((z) => Math.max(z - 1, 10));
  const handleRecenter = () => {
    if (locationSource === "gps" && realTimeLocation) {
      setCenterCoords({ lat: realTimeLocation.lat, lng: realTimeLocation.lng });
    } else {
      setCenterCoords(defaultCenter);
    }
    setZoomLevel(15);
  };

  // Google Maps URL
  const googleMapTypeParam = mapMode === "satellite" ? "k" : "m";
  const googleMapsEmbedUrl = `https://maps.google.com/maps?q=${centerCoords.lat},${centerCoords.lng}&t=${googleMapTypeParam}&z=${zoomLevel}&ie=UTF8&iwloc=&output=embed`;
  const externalGoogleMapsUrl = `https://www.google.com/maps?q=${centerCoords.lat},${centerCoords.lng}&t=${googleMapTypeParam}`;

  // Dark tactical filter
  const getMapFilterStyle = () => {
    if (mapMode === "dark_tactical") {
      return "invert(93%) hue-rotate(185deg) contrast(135%) brightness(80%) saturate(25%)";
    }
    if (mapMode === "satellite") {
      return "contrast(110%) brightness(88%)";
    }
    return "none";
  };

  return (
    <div
      className={`tactical-panel flex flex-col overflow-hidden relative select-none ${className}`}
      style={{ minHeight: isExpanded ? "640px" : "480px" }}
    >
      {/* ── Top Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-[#162035] bg-[#070b16] z-20">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded-[3px] bg-cyan-950/80 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <circle cx="12" cy="12" r="3" fill="#00e5ff" fillOpacity="0.4" />
              <path d="M12 3v9l6 3" />
            </svg>
          </div>
          <div className="flex items-center gap-1.5">
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-slate-100">
              Live Map Overview
            </h2>
            <span className="text-slate-600">·</span>
            <span className="text-[9px] font-mono text-cyan-400 font-bold">
              {mapMode === "dark_tactical" ? "DARK TACTICAL GRID" : mapMode.toUpperCase()}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {/* Layer Switcher */}
          <div className="flex items-center bg-[#090e1b] rounded-[3px] p-0.5 border border-[#162035] text-[9px] font-mono">
            <button
              onClick={() => setMapMode("dark_tactical")}
              className={`px-2 py-0.5 rounded-[2px] font-bold uppercase transition-all cursor-pointer ${
                mapMode === "dark_tactical"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/60 shadow-[0_0_6px_rgba(0,229,255,0.2)]"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              ⬛ Tactical
            </button>
            <button
              onClick={() => setMapMode("satellite")}
              className={`px-2 py-0.5 rounded-[2px] font-bold uppercase transition-all cursor-pointer ${
                mapMode === "satellite"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/60 shadow-[0_0_6px_rgba(0,229,255,0.2)]"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              🛰️ Sat
            </button>
            <button
              onClick={() => setMapMode("roadmap")}
              className={`px-2 py-0.5 rounded-[2px] font-bold uppercase transition-all cursor-pointer ${
                mapMode === "roadmap"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/60 shadow-[0_0_6px_rgba(0,229,255,0.2)]"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              🗺️ Map
            </button>
          </div>

          {/* Live GPS Status */}
          <button
            onClick={acquireRealTimeLocation}
            disabled={isLocating}
            className={`px-2 py-0.5 rounded-[3px] text-[9px] font-mono font-bold uppercase tracking-wider flex items-center gap-1 transition-all cursor-pointer border ${
              locationSource === "gps"
                ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/50 shadow-[0_0_6px_rgba(16,185,129,0.2)]"
                : "bg-[#090e1b] text-slate-300 hover:text-white border-[#162035] hover:border-cyan-500/40"
            }`}
            title="Live GPS location tracking"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isLocating
                  ? "bg-amber-400 animate-spin"
                  : locationSource === "gps"
                  ? "bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse"
                  : "bg-cyan-400"
              }`}
            />
            <span>{isLocating ? "ACQUIRING..." : locationSource === "gps" ? "LIVE GPS ACTIVE" : "📍 GPS"}</span>
          </button>

          {/* Expand Toggle */}
          {onToggleExpand && (
            <button
              onClick={onToggleExpand}
              className="px-1.5 py-0.5 rounded-[3px] text-[9px] font-mono text-slate-300 hover:text-cyan-300 bg-[#090e1b] border border-[#162035] hover:border-cyan-500/40 transition-colors cursor-pointer"
              title={isExpanded ? "Collapse" : "Expand"}
            >
              {isExpanded ? "⛶ COLLAPSE" : "⛶ EXPAND"}
            </button>
          )}
        </div>
      </div>

      {/* ── Main Map Viewport ── */}
      <div className="relative flex-1 bg-[#0a0d16] overflow-hidden" style={{ minHeight: isExpanded ? "560px" : "420px" }}>
        {/* Google Maps iframe — pointer-events disabled to prevent internal drag that causes marker drift */}
        <div className="absolute inset-0 w-full h-full pointer-events-none">
          <iframe
            key={`${centerCoords.lat}-${centerCoords.lng}-${mapMode}-${zoomLevel}`}
            title="Tactical Map Feed"
            src={googleMapsEmbedUrl}
            className="w-full h-full border-0 select-none pointer-events-none"
            style={{
              filter: getMapFilterStyle(),
            }}
            loading="lazy"
          />
        </div>

        {/* Dark Vignette */}
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_center,transparent_60%,rgba(5,8,17,0.55)_100%)] z-10" />

        {/* Floating Zoom & Center Controls */}
        <div className="absolute top-3 left-3 z-30 flex flex-col gap-1">
          <button
            onClick={handleZoomIn}
            title="Zoom In"
            className="w-6 h-6 rounded-[2px] bg-[#070b16]/95 hover:bg-[#131d36] border border-[#1e2e4f] text-slate-200 text-xs font-bold flex items-center justify-center transition-colors shadow-lg cursor-pointer font-mono"
          >
            +
          </button>
          <button
            onClick={handleZoomOut}
            title="Zoom Out"
            className="w-6 h-6 rounded-[2px] bg-[#070b16]/95 hover:bg-[#131d36] border border-[#1e2e4f] text-slate-200 text-xs font-bold flex items-center justify-center transition-colors shadow-lg cursor-pointer font-mono"
          >
            −
          </button>
          <button
            onClick={handleRecenter}
            title="Recenter Map"
            className="w-6 h-6 rounded-[2px] bg-[#070b16]/95 hover:bg-[#131d36] border border-[#1e2e4f] text-cyan-400 text-[10px] flex items-center justify-center transition-colors shadow-lg cursor-pointer"
          >
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="7" />
              <line x1="12" y1="2" x2="12" y2="5" />
              <line x1="12" y1="19" x2="12" y2="22" />
              <line x1="2" y1="12" x2="5" y2="12" />
              <line x1="19" y1="12" x2="22" y2="12" />
            </svg>
          </button>
        </div>

        {/* ── Camera Markers: GPS-Pinned at Map Center (Static, Won't Drift) ── */}
        <div className="absolute inset-0 pointer-events-none z-20">
          {displayCameras.map((cam) => {
            const isAlert = isCameraAlerting(cam.camera_uid);
            const isSelected = selectedCameraUid.toLowerCase() === cam.camera_uid.toLowerCase();

            {/* GPS-pinned: Camera marker is ALWAYS at exact center of the map container.
                The iframe always centers on centerCoords, so the marker at 50%/50% is
                perfectly aligned with the GPS coordinate. This is static and never drifts
                when zooming/dragging because pointer-events are disabled on the iframe. */}

            return (
              <div
                key={cam.camera_uid}
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  transform: "translate(-50%, -50%)",
                }}
                className="pointer-events-auto cursor-pointer group"
                onClick={() => {
                  if (onSelectCamera) onSelectCamera(cam);
                  setActiveTooltip(activeTooltip === cam.camera_uid ? null : cam.camera_uid);
                }}
              >
                {/* Outer Reticle Ring — 20px static marker, no drift */}
                <div
                  className={`absolute rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2 transition-colors ${
                    isAlert
                      ? "border-2 border-rose-500 bg-rose-500/20 shadow-[0_0_16px_rgba(244,63,94,0.7)] animate-pulse"
                      : "border border-cyan-400/60 bg-cyan-500/8 shadow-[0_0_8px_rgba(0,229,255,0.2)]"
                  }`}
                  style={{ width: "20px", height: "20px", top: "50%", left: "50%" }}
                />

                {/* Subtle Ping Ring (alert only) */}
                {isAlert && (
                  <div
                    className="absolute rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2 border border-rose-500/50 animate-ping [animation-duration:1.5s]"
                    style={{ width: "36px", height: "36px", top: "50%", left: "50%" }}
                  />
                )}

                {/* Crosshair Ticks — small tactical reticle */}
                <div
                  className={`absolute pointer-events-none -translate-x-1/2 -translate-y-1/2 ${
                    isAlert ? "text-rose-400" : "text-cyan-400/70"
                  }`}
                  style={{ top: "50%", left: "50%", width: "16px", height: "16px" }}
                >
                  <svg className="w-full h-full" viewBox="0 0 24 24">
                    <line x1="12" y1="1" x2="12" y2="6" stroke="currentColor" strokeWidth="1.5" />
                    <line x1="12" y1="18" x2="12" y2="23" stroke="currentColor" strokeWidth="1.5" />
                    <line x1="1" y1="12" x2="6" y2="12" stroke="currentColor" strokeWidth="1.5" />
                    <line x1="18" y1="12" x2="23" y2="12" stroke="currentColor" strokeWidth="1.5" />
                  </svg>
                </div>

                {/* Central Core Pip — 8px fixed */}
                <div className="relative flex items-center justify-center">
                  <div
                    className={`w-2 h-2 rounded-full transition-all ${
                      isAlert
                        ? "bg-rose-500 shadow-[0_0_12px_#f43f5e] border border-white animate-pulse"
                        : isSelected
                        ? "bg-cyan-400 shadow-[0_0_8px_#00e5ff] border border-white"
                        : "bg-cyan-500 shadow-[0_0_6px_#00e5ff] border border-slate-900"
                    }`}
                  >
                    <div
                      className={`w-0.5 h-0.5 rounded-full mx-auto mt-[1px] ${
                        isAlert ? "bg-white" : "bg-[#050811]"
                      }`}
                    />
                  </div>

                  {/* Camera ID Badge — compact, always visible */}
                  <div
                    className={`absolute top-3 whitespace-nowrap px-1 py-px rounded-[2px] text-[7px] font-mono font-bold tracking-wider pointer-events-none shadow-md ${
                      isAlert
                        ? "bg-rose-950 text-rose-200 border border-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.5)] animate-pulse"
                        : isSelected
                        ? "bg-[#070b16] text-cyan-300 border border-cyan-400"
                        : "bg-[#070b16]/90 text-slate-300 border border-[#162035] group-hover:text-white"
                    }`}
                  >
                    {isAlert ? `🚨 ${cam.camera_uid.toUpperCase()} · INTRUSION` : cam.camera_uid.toUpperCase()}
                  </div>
                </div>

                {/* Tooltip on hover/click */}
                <div
                  className={`absolute bottom-8 left-1/2 -translate-x-1/2 w-40 p-1.5 rounded-[3px] bg-[#070b16]/95 border shadow-2xl z-30 pointer-events-none transition-all font-mono text-[8px] ${
                    isAlert
                      ? "border-rose-500 text-rose-200"
                      : "border-[#1e2e4f] text-slate-300"
                  } ${
                    activeTooltip === cam.camera_uid
                      ? "opacity-100 translate-y-0"
                      : "opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-[#162035] pb-0.5 mb-0.5">
                    <span className="font-bold text-white uppercase">{cam.camera_uid}</span>
                    <span
                      className={`text-[7px] font-bold px-1 rounded ${
                        isAlert
                          ? "bg-rose-900 text-rose-200 border border-rose-500 animate-pulse"
                          : "bg-emerald-950 text-emerald-300 border border-emerald-700/60"
                      }`}
                    >
                      {isAlert ? "⚠ BREACH" : "ACTIVE"}
                    </span>
                  </div>
                  <p className="text-[7px] text-slate-300 truncate">{cam.name}</p>
                  <div className="flex items-center justify-between text-[7px] text-slate-400 mt-0.5 pt-0.5 border-t border-[#162035]">
                    <span>GPS:</span>
                    <span className="text-cyan-300 font-bold">
                      {centerCoords.lat.toFixed(5)}°, {centerCoords.lng.toFixed(5)}°
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Bottom Telemetry Strip ── */}
        <div className="absolute bottom-2 left-2 right-2 z-20 flex flex-wrap items-center justify-between gap-1.5 pointer-events-none">
          {/* Coordinates HUD */}
          <div className="bg-[#050811]/95 backdrop-blur-md px-2 py-1 rounded-[3px] border border-[#162035] text-[9px] font-mono text-slate-300 flex items-center gap-2 pointer-events-auto">
            <div className="flex items-center gap-1">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  locationSource === "gps" ? "bg-emerald-400 animate-pulse" : "bg-cyan-400"
                }`}
              />
              <span className="text-slate-400 text-[8px] uppercase">
                {locationSource === "gps" ? "LIVE GPS:" : "SECTOR:"}
              </span>
              <span className="text-white font-bold">
                {centerCoords.lat.toFixed(5)}°N, {centerCoords.lng.toFixed(5)}°E
              </span>
              {realTimeLocation?.accuracy && locationSource === "gps" && (
                <span className="text-[8px] text-emerald-400">
                  (±{realTimeLocation.accuracy}m)
                </span>
              )}
            </div>

            {/* Alert badge with Silence button */}
            {activeAlert ? (
              <div className="flex items-center gap-1.5">
                <span className="flex items-center gap-1 text-rose-400 font-bold bg-rose-950/80 px-1 py-px rounded border border-rose-500/60 animate-pulse text-[8px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                  BREACH: {(() => {
                    let dj: Record<string, unknown> | undefined;
                    if (typeof activeAlert.data_json === "string") {
                      try { dj = JSON.parse(activeAlert.data_json); } catch { /* */ }
                    } else if (activeAlert.data_json && typeof activeAlert.data_json === "object") {
                      dj = activeAlert.data_json as Record<string, unknown>;
                    }
                    return ((dj?.camera_uid || dj?.camera_id || "CAM") as string).toUpperCase();
                  })()}
                </span>
                <button
                  onClick={handleSilenceAlert}
                  className="px-1.5 py-px rounded-[2px] bg-sky-950 hover:bg-sky-900 border border-sky-600 text-sky-200 text-[8px] font-mono uppercase cursor-pointer pointer-events-auto"
                  title="Acknowledge and silence alert"
                >
                  ✓ ACK
                </button>
              </div>
            ) : (
              <span className="text-emerald-400 font-bold text-[8px] hidden sm:inline">
                ● NOMINAL
              </span>
            )}
          </div>

          {/* External Google Maps Link */}
          <a
            href={externalGoogleMapsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-[#050811]/95 hover:bg-[#0d1424] backdrop-blur-md px-2 py-1 rounded-[3px] border border-[#162035] hover:border-cyan-500/50 text-[9px] font-mono text-cyan-300 hover:text-cyan-200 flex items-center gap-1 transition-colors pointer-events-auto shadow-md"
          >
            <span>Open in Google Maps</span>
            <span className="text-[10px]">↗</span>
          </a>
        </div>
      </div>

      {/* Geolocation Error Notice */}
      {locationError && (
        <div className="px-2.5 py-0.5 bg-amber-950/40 border-t border-amber-900/40 text-[8px] font-mono text-amber-300 flex items-center justify-between">
          <span>ℹ {locationError}</span>
          <button
            onClick={() => setLocationError(null)}
            className="text-amber-400 hover:text-white font-bold cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
