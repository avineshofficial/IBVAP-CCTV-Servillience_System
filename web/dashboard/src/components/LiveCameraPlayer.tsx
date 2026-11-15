"use client";
import React, { useEffect, useState, useRef, useSyncExternalStore } from "react";
import { getCameraStreamUrl, getCameraFrameUrl, getMediaUrl } from "@/lib/api";

interface LiveCameraPlayerProps {
  cameraUid: string;
  cameraName?: string;
  className?: string;
}

const emptySubscribe = () => () => {};

function LiveCameraPlayerInternal({
  cameraUid,
  cameraName = "Optical Sensor",
  className = "",
}: LiveCameraPlayerProps) {
  const isClient = useSyncExternalStore(emptySubscribe, () => true, () => false);
  const [isReceiving, setIsReceiving] = useState<boolean>(false);
  const [retryCount, setRetryCount] = useState<number>(0);
  const [useFallback, setUseFallback] = useState<boolean>(false);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);

  const errorCountRef = useRef<number>(0);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const fallbackTimerRef = useRef<NodeJS.Timeout | null>(null);
  const activeFallbackBlobRef = useRef<string | null>(null);

  const streamUrl = retryCount > 0
    ? `${getCameraStreamUrl(cameraUid)}?_r=${retryCount}`
    : getCameraStreamUrl(cameraUid);

  // Fallback Polling Loop (only triggered if native multipart streaming is blocked)
  useEffect(() => {
    if (!useFallback) {
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
      if (activeFallbackBlobRef.current) {
        URL.revokeObjectURL(activeFallbackBlobRef.current);
        activeFallbackBlobRef.current = null;
      }
      return;
    }

    let isMounted = true;
    const fetchFallbackFrame = async () => {
      if (!isMounted) return;
      const t = Date.now();
      try {
        let res = await fetch(`${getCameraFrameUrl(cameraUid)}?_t=${t}`, { cache: "no-store" });
        if (!res.ok) {
          res = await fetch(`${getMediaUrl(`/media/live_${cameraUid}.jpg`)}?_t=${t}`, { cache: "no-store" });
        }
        if (res.ok) {
          const blob = await res.blob();
          if (isMounted && blob.size > 200) {
            const nextUrl = URL.createObjectURL(blob);
            setFallbackUrl(nextUrl);
            setIsReceiving(true);
            if (activeFallbackBlobRef.current) {
              URL.revokeObjectURL(activeFallbackBlobRef.current);
            }
            activeFallbackBlobRef.current = nextUrl;
          }
        }
      } catch {
        /* fallback retry */
      } finally {
        if (isMounted && useFallback) {
          fallbackTimerRef.current = setTimeout(fetchFallbackFrame, 40);
        }
      }
    };

    fetchFallbackFrame();

    return () => {
      isMounted = false;
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
      if (activeFallbackBlobRef.current) {
        URL.revokeObjectURL(activeFallbackBlobRef.current);
        activeFallbackBlobRef.current = null;
      }
    };
  }, [useFallback, cameraUid]);

  // Handle stream error & automatic reconnection
  const handleStreamError = () => {
    setIsReceiving(false);
    errorCountRef.current += 1;

    // After 3 failed stream connection attempts, activate fallback mode
    if (errorCountRef.current >= 4) {
      setUseFallback(true);
      return;
    }

    // Otherwise, retry native stream connection after a short backoff
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      setRetryCount((prev) => prev + 1);
    }, 1500);
  };

  const handleStreamLoad = () => {
    setIsReceiving(true);
    errorCountRef.current = 0;
  };

  return (
    <div
      className={`relative aspect-video w-full rounded-[4px] overflow-hidden bg-[#03060c] tactical-hud shadow-[0_8px_30px_rgba(0,0,0,0.8)] border border-[#162035] ${className}`}
    >
      {/* Precision corner reticles */}
      <div className="corner-bracket-tl"></div>
      <div className="corner-bracket-tr"></div>
      <div className="corner-bracket-bl"></div>
      <div className="corner-bracket-br"></div>

      {/* Calibrated Center Crosshair */}
      <div className="reticle-crosshair"></div>

      {/* Primary Native Low-Latency MJPEG Stream */}
      {isClient && !useFallback && (
        <img
          key={retryCount}
          src={streamUrl}
          alt={`Live Feed from ${cameraName}`}
          className={`w-full h-full object-contain select-none transition-opacity duration-300 ${
            isReceiving ? "opacity-100" : "opacity-0 absolute inset-0 pointer-events-none"
          }`}
          onLoad={handleStreamLoad}
          onError={handleStreamError}
        />
      )}

      {/* Fallback Single-Frame Player */}
      {isClient && useFallback && fallbackUrl && (
        <img
          src={fallbackUrl}
          alt={`Live Feed from ${cameraName}`}
          className="w-full h-full object-contain select-none"
        />
      )}

      {/* Tactical Waiting HUD (shown when sensor frames are offline) */}
      {!isReceiving && (
        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center space-y-2.5 bg-[#040711]/90">
          <div className="relative flex items-center justify-center w-12 h-12 rounded-[4px] border border-cyan-500/30 bg-cyan-950/20">
            <span className="w-6 h-6 rounded-full border-2 border-t-cyan-400 border-r-transparent border-b-cyan-500/20 border-l-transparent animate-spin"></span>
            <span className="absolute w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping"></span>
          </div>
          <div>
            <p className="text-[11px] font-mono font-bold uppercase tracking-widest text-cyan-400">
              [WAITING FOR OPTICAL SENSOR SIGNAL]
            </p>
            <p className="text-[10px] text-slate-400 mt-0.5 max-w-sm font-mono">
              Channel {cameraUid.toUpperCase()} online. Awaiting camera sensor frames from Edge pipeline.
            </p>
          </div>
          <span className="text-[9px] font-mono text-slate-500 bg-[#070b16] px-2 py-0.5 rounded-[2px] border border-[#162035]">
            SOURCE: {cameraUid.toUpperCase()} · 1080P GRID
          </span>
        </div>
      )}

      {/* Live Status Overlay Tag (Bottom Left) */}
      <div className="absolute bottom-2.5 left-2.5 flex items-center gap-2 z-20">
        <div className="bg-[#050811]/90 backdrop-blur-md px-2 py-1 rounded-[3px] border border-[#162035] flex items-center gap-2 text-[10px] font-mono">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              isReceiving ? "bg-emerald-400 shadow-[0_0_6px_#10b981] animate-pulse" : "bg-amber-400"
            }`}
          ></span>
          <span className="text-white font-bold">
            {isReceiving ? "LIVE OPTICAL STREAM" : "CONNECTING..."}
          </span>
          <span className="text-slate-600">·</span>
          <span className={isReceiving ? "text-emerald-400 font-bold" : "text-slate-400"}>
            {isReceiving ? "AI TRACKING ACTIVE" : "AWAITING SENSOR"}
          </span>
        </div>
      </div>

      {/* Telemetry Badge (Bottom Right) */}
      <div className="absolute bottom-2.5 right-2.5 z-20">
        <div className="bg-[#050811]/90 backdrop-blur-md px-2 py-1 rounded-[3px] border border-[#162035] text-[10px] font-mono text-cyan-300 font-bold font-mono-tabular">
          {isReceiving
            ? `STREAM: ${useFallback ? "FALLBACK (20 FPS)" : "FLUENT (25-30 FPS)"}`
            : `CHANNEL: ${cameraUid.toUpperCase()}`}
        </div>
      </div>
    </div>
  );
}

export default function LiveCameraPlayer(props: LiveCameraPlayerProps) {
  return <LiveCameraPlayerInternal key={props.cameraUid} {...props} />;
}
