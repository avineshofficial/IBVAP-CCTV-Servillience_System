"use client";
import React, { useEffect, useState, useCallback } from "react";
import { getCameras, createCamera } from "@/lib/api";
import type { Camera } from "@/lib/api";
import LiveCameraPlayer from "@/components/LiveCameraPlayer";

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedCam, setSelectedCam] = useState<Camera | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCam, setNewCam] = useState({
    name: "",
    camera_uid: "",
    bop_id: "bop_alpha",
    rtsp_url: "",
    is_ptz: false,
    lat: 26.8467,
    lng: 80.9462,
  });

  const loadCameras = useCallback(async () => {
    try {
      const c = await getCameras();
      if (Array.isArray(c) && c.length > 0) {
        setCameras(c);
        setSelectedCam((prev) => {
          if (!prev) return c[0];
          const found = c.find((item) => item.camera_uid === prev.camera_uid);
          return found || c[0];
        });
      }
    } catch {
      /* api error fallback */
    }
  }, []);

  useEffect(() => {
    let isSubscribed = true;
    async function init() {
      try {
        const c = await getCameras();
        if (isSubscribed && Array.isArray(c) && c.length > 0) {
          setCameras(c);
          setSelectedCam((prev) => {
            if (!prev) return c[0];
            const found = c.find((item) => item.camera_uid === prev.camera_uid);
            return found || c[0];
          });
        }
      } catch {
        /* fallback */
      }
    }

    init();
    const interval = setInterval(loadCameras, 4000);
    return () => {
      isSubscribed = false;
      clearInterval(interval);
    };
  }, [loadCameras]);

  async function handleAddCamera(e: React.FormEvent) {
    e.preventDefault();
    if (!newCam.camera_uid || !newCam.name) return;
    try {
      await createCamera(newCam);
      setShowAddModal(false);
      setNewCam({
        name: "",
        camera_uid: "",
        bop_id: "bop_alpha",
        rtsp_url: "",
        is_ptz: false,
        lat: 26.8467,
        lng: 80.9462,
      });
      await loadCameras();
    } catch (err) {
      console.error("Camera creation failed:", err);
    }
  }

  const mainCam = selectedCam || (cameras.length > 0 ? cameras[0] : ({
    id: 1,
    name: "Primary Optical Sensor (Lenovo 300 FHD Live)",
    camera_uid: "cam_01",
    bop_id: "bop_alpha",
    status: "online",
    is_ptz: false,
  } as Camera));

  const sideCameras = cameras.filter((c) => c.camera_uid !== mainCam.camera_uid);

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#162035] pb-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_6px_#00e5ff]"></span>
            <h1 className="text-sm font-bold uppercase tracking-widest text-slate-100 font-mono">
              OPTICAL SURVEILLANCE SENSOR GRID
            </h1>
            <span className="badge-status badge-online">
              <span className="status-pip status-pip-online"></span> {cameras.length} CONFIGURED
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-mono mt-0.5">
            Tactical optical sensor feeds · Zero-delay MJPEG ingestion · Multi-channel perimeter surveillance
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setShowAddModal(true)}
            className="btn-tactical-primary text-xs font-mono uppercase tracking-wider"
          >
            + Register Optical Sensor
          </button>
        </div>
      </div>

      {/* Main Viewport & Side Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4 items-start">
        {/* Main Prominent Camera View (3 Columns) */}
        <div className="xl:col-span-3 space-y-3">
          <div className="tactical-panel p-3.5 space-y-3">
            {/* Viewport Top Bar */}
            <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[#162035] pb-2.5 text-xs font-mono">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse"></span>
                <span className="font-bold text-white uppercase text-xs tracking-wider">
                  {mainCam.name}
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-cyan-400 font-bold bg-[#0c1424] px-1.5 py-0.2 rounded border border-cyan-800/40 text-[11px]">
                  {mainCam.camera_uid.toUpperCase()}
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-400 uppercase text-[10px]">{mainCam.bop_id}</span>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="px-1.5 py-0.5 rounded-[2px] bg-[#090f1d] border border-cyan-800/50 text-cyan-300 text-[9px] font-bold">
                  FHD 1080P · 95° WIDE FOV
                </span>
                <span className="px-1.5 py-0.5 rounded-[2px] bg-[#090f1d] border border-emerald-800/50 text-emerald-400 text-[9px] font-bold">
                  AI BOUNDING BOX ON
                </span>
              </div>
            </div>

            {/* Live Camera Viewport */}
            <LiveCameraPlayer
              cameraUid={mainCam.camera_uid}
              cameraName={mainCam.name}
            />

            {/* Bottom Telemetry Strip */}
            <div className="flex flex-wrap items-center justify-between text-xs font-mono text-slate-400 pt-2 border-t border-[#162035]">
              <div className="flex items-center gap-3 text-[11px]">
                <span>
                  STATUS: <strong className="text-emerald-400">{mainCam.status.toUpperCase()}</strong>
                </span>
                <span className="text-slate-600">·</span>
                <span>
                  PTZ: <strong className="text-slate-200">{mainCam.is_ptz ? "ENABLED" : "FIXED"}</strong>
                </span>
                {mainCam.lat && mainCam.lng && (
                  <>
                    <span className="text-slate-600">·</span>
                    <span>
                      GPS: <strong className="text-slate-200 font-mono-tabular">{mainCam.lat.toFixed(4)}°N, {mainCam.lng.toFixed(4)}°E</strong>
                    </span>
                  </>
                )}
              </div>
              <span className="text-slate-500 text-[10px]">
                {sideCameras.length > 0 ? "Select any side channel to switch feed" : "Live Primary Stream Active"}
              </span>
            </div>
          </div>
        </div>

        {/* Side Channel Section (1 Column) */}
        <div className="space-y-3">
          <div className="tactical-panel p-3.5 space-y-3">
            <div className="flex items-center justify-between border-b border-[#162035] pb-2">
              <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-slate-100">
                {sideCameras.length > 0 ? `Side Channels (${sideCameras.length})` : "Sensor Health"}
              </h2>
              <span className="text-[9px] font-mono text-cyan-400 font-bold bg-cyan-950/60 px-1.5 py-0.2 rounded border border-cyan-800/40">
                {sideCameras.length > 0 ? "CLICK TO SWITCH" : "TELEMETRY"}
              </span>
            </div>

            {sideCameras.length > 0 ? (
              <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
                {sideCameras.map((cam) => (
                  <div
                    key={cam.id}
                    onClick={() => setSelectedCam(cam)}
                    className="rounded-[4px] overflow-hidden border border-[#162035] bg-[#090e1b] hover:border-cyan-400 cursor-pointer transition-all"
                  >
                    <div className="flex items-center justify-between px-2.5 py-1 bg-[#060913] text-xs font-mono">
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                        <span className="font-bold text-white uppercase text-[11px]">{cam.camera_uid}</span>
                      </div>
                      <span className="text-[9px] text-slate-400 uppercase">{cam.bop_id}</span>
                    </div>
                    <LiveCameraPlayer cameraUid={cam.camera_uid} cameraName={cam.name} />
                    <div className="p-1.5 text-[11px] bg-[#060913] text-slate-300 truncate font-mono">
                      {cam.name}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2.5 text-xs font-mono">
                <div className="p-2.5 rounded-[4px] bg-[#070b16] border border-[#162035] space-y-2">
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px]">Optical Link:</span>
                    <span className="text-emerald-400 font-bold text-[11px]">● CONNECTED</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px]">Active Device:</span>
                    <span className="text-slate-200 text-[11px]">Live Webcam / CCTV</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px]">Neural Model:</span>
                    <span className="text-cyan-400 text-[11px]">YOLOv11n (384p)</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px]">Frame Rate:</span>
                    <span className="text-emerald-400 font-mono-tabular text-[11px]">25–30 FPS Fluent</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px]">Buffer Pipeline:</span>
                    <span className="text-cyan-300 text-[11px]">Zero-Delay MJPEG</span>
                  </div>
                </div>

                <div className="p-2.5 rounded-[4px] bg-[#060913] border border-cyan-900/30 text-slate-400 space-y-1">
                  <p className="text-[10px] font-bold text-cyan-300 uppercase tracking-wider font-mono">
                    📡 Multi-Camera Support
                  </p>
                  <p className="text-[10px] text-slate-400 leading-relaxed font-mono">
                    Currently streaming optical channel <strong>{mainCam.camera_uid}</strong>. Click <strong>+ Register Optical Sensor</strong> above to attach additional CCTV cameras or RTSP video streams.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Add Camera Modal */}
      {showAddModal && (
        <div className="defense-modal-backdrop">
          <div className="defense-modal max-w-lg p-5 space-y-3.5">
            <div className="flex items-center justify-between border-b border-[#162035] pb-2.5">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2 font-mono">
                <span className="text-cyan-400">📹</span> Register Optical Sensor
              </h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white text-sm font-bold font-mono cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleAddCamera} className="space-y-3 text-xs font-mono">
              <div>
                <label className="block text-slate-400 mb-1 text-[11px]">SENSOR NAME</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. North Gate Perimeter Cam"
                  value={newCam.name}
                  onChange={(e) => setNewCam({ ...newCam, name: e.target.value })}
                  className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="block text-slate-400 mb-1 text-[11px]">CAMERA UID</label>
                  <input
                    type="text"
                    required
                    placeholder="cam_02"
                    value={newCam.camera_uid}
                    onChange={(e) => setNewCam({ ...newCam, camera_uid: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 text-[11px]">BOP SECTOR ID</label>
                  <input
                    type="text"
                    required
                    value={newCam.bop_id}
                    onChange={(e) => setNewCam({ ...newCam, bop_id: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 text-[11px]">RTSP STREAM URL (OPTIONAL)</label>
                <input
                  type="text"
                  placeholder="rtsp://admin:pass@192.168.1.100:554/live"
                  value={newCam.rtsp_url}
                  onChange={(e) => setNewCam({ ...newCam, rtsp_url: e.target.value })}
                  className="w-full px-2.5 py-1.5 rounded-[3px] bg-[#070b16] border border-[#162035] text-white focus:border-cyan-400 outline-none text-xs"
                />
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-[#162035]">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="btn-tactical-outline text-xs"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-tactical-primary text-xs">
                  Save & Connect Sensor
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
