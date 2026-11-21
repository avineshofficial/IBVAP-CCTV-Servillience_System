"use client";
import React, { useEffect, useState, useRef, useSyncExternalStore } from "react";
import { getCameraStreamUrl } from "@/lib/api";

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
  const [useMjpegFallback, setUseMjpegFallback] = useState<boolean>(false);
  const [mjpegRetry, setMjpegRetry] = useState<number>(0);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const fpsBadgeRef = useRef<HTMLSpanElement | null>(null);

  // Refs for zero-rerender, zero-queue-buildup frame rendering
  const wsRef = useRef<WebSocket | null>(null);
  const rafIdRef = useRef<number>(0);
  const isDecodingRef = useRef<boolean>(false);
  const pendingBitmapRef = useRef<ImageBitmap | null>(null);
  const hasReceivedFrameRef = useRef<boolean>(false);
  const wsFailCountRef = useRef<number>(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frameCounterRef = useRef<number>(0);
  const lastFpsTimeRef = useRef<number>(0);

  const streamUrl = getCameraStreamUrl(cameraUid);
  const wsUrl = streamUrl.replace(/^http/, "ws").replace(/\/stream$/, "/ws");
  const activeMjpegUrl = mjpegRetry > 0 ? `${streamUrl}?_r=${mjpegRetry}` : streamUrl;

  // Primary: Binary WebSocket -> createImageBitmap -> requestAnimationFrame -> <canvas>
  // Zero React state updates per frame; closes old bitmaps immediately to keep memory flat.
  useEffect(() => {
    if (!isClient || useMjpegFallback) return;

    let isMounted = true;
    hasReceivedFrameRef.current = false;
    frameCounterRef.current = 0;
    lastFpsTimeRef.current = performance.now();

    const drawLoop = () => {
      if (!isMounted) return;

      const bitmap = pendingBitmapRef.current;
      const canvas = canvasRef.current;

      if (bitmap && canvas) {
        pendingBitmapRef.current = null;
        if (!ctxRef.current) {
          ctxRef.current = canvas.getContext("2d", { alpha: false });
        }
        const ctx = ctxRef.current;
        if (ctx) {
          if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
          }
          ctx.drawImage(bitmap, 0, 0);
        }
        bitmap.close();

        if (!hasReceivedFrameRef.current) {
          hasReceivedFrameRef.current = true;
          setIsReceiving(true);
        }

        frameCounterRef.current += 1;
        const now = performance.now();
        const elapsed = now - lastFpsTimeRef.current;
        if (elapsed >= 1000) {
          const fps = Math.round((frameCounterRef.current * 1000) / elapsed);
          frameCounterRef.current = 0;
          lastFpsTimeRef.current = now;
          if (fpsBadgeRef.current) {
            fpsBadgeRef.current.textContent = `STREAM: LIVE (${fps} FPS)`;
          }
        }
      }

      rafIdRef.current = requestAnimationFrame(drawLoop);
    };

    const connectWs = () => {
      if (!isMounted) return;
      try {
        const ws = new WebSocket(wsUrl);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) {
            ws.close();
            return;
          }
          wsFailCountRef.current = 0;
        };

        ws.onmessage = (event: MessageEvent) => {
          if (!isMounted) return;
          const data = event.data;
          if (!(data instanceof ArrayBuffer) || data.byteLength < 100) return;

          // Drop incoming frame if previous decode is still running (prevents latency buildup)
          if (isDecodingRef.current) return;
          isDecodingRef.current = true;

          const blob = new Blob([data], { type: "image/jpeg" });
          createImageBitmap(blob)
            .then((bitmap) => {
              if (!isMounted) {
                bitmap.close();
                return;
              }
              const old = pendingBitmapRef.current;
              pendingBitmapRef.current = bitmap;
              if (old) old.close();
            })
            .catch(() => {
              /* ignore corrupted frame */
            })
            .finally(() => {
              isDecodingRef.current = false;
            });
        };

        ws.onerror = () => {
          /* handled in onclose */
        };

        ws.onclose = () => {
          if (!isMounted) return;
          wsRef.current = null;
          wsFailCountRef.current += 1;
          if (wsFailCountRef.current >= 3) {
            setUseMjpegFallback(true);
            return;
          }
          reconnectTimerRef.current = setTimeout(connectWs, 1200);
        };
      } catch {
        wsFailCountRef.current += 1;
        if (wsFailCountRef.current >= 3) {
          setUseMjpegFallback(true);
        } else {
          reconnectTimerRef.current = setTimeout(connectWs, 1200);
        }
      }
    };

    rafIdRef.current = requestAnimationFrame(drawLoop);
    connectWs();

    return () => {
      isMounted = false;
      cancelAnimationFrame(rafIdRef.current);
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* ignore */
        }
        wsRef.current = null;
      }
      if (pendingBitmapRef.current) {
        pendingBitmapRef.current.close();
        pendingBitmapRef.current = null;
      }
      ctxRef.current = null;
    };
  }, [isClient, useMjpegFallback, wsUrl]);

  // Guaranteed teardown for MJPEG fallback <img> so browser immediately closes multipart HTTP stream on unmount
  useEffect(() => {
    const imgEl = imgRef.current;
    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (imgEl) {
        imgEl.src = "";
      }
    };
  }, [useMjpegFallback, activeMjpegUrl]);

  const handleMjpegError = () => {
    setIsReceiving(false);
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      setMjpegRetry((prev) => prev + 1);
    }, 1500);
  };

  const handleMjpegLoad = () => {
    setIsReceiving(true);
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

      {/* Primary: Zero-Stutter Binary WebSocket Canvas Player */}
      {isClient && !useMjpegFallback && (
        <canvas
          ref={canvasRef}
          aria-label={`Live Feed from ${cameraName}`}
          className={`w-full h-full object-contain select-none transition-opacity duration-200 ${
            isReceiving ? "opacity-100" : "opacity-0 absolute inset-0 pointer-events-none"
          }`}
        />
      )}

      {/* Fallback: Single Stable Native MJPEG <img> Stream (zero per-frame setState) */}
      {isClient && useMjpegFallback && (
        <img
          ref={imgRef}
          key={mjpegRetry}
          src={activeMjpegUrl}
          alt={`Live Feed from ${cameraName}`}
          className={`w-full h-full object-contain select-none transition-opacity duration-200 ${
            isReceiving ? "opacity-100" : "opacity-0 absolute inset-0 pointer-events-none"
          }`}
          onLoad={handleMjpegLoad}
          onError={handleMjpegError}
        />
      )}

      {/* Tactical Waiting HUD (shown until first frame arrives) */}
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

      {/* Telemetry Badge (Bottom Right) — updated via ref at 1 Hz (zero React re-renders per frame) */}
      <div className="absolute bottom-2.5 right-2.5 z-20">
        <div className="bg-[#050811]/90 backdrop-blur-md px-2 py-1 rounded-[3px] border border-[#162035] text-[10px] font-mono text-cyan-300 font-bold font-mono-tabular">
          <span ref={fpsBadgeRef}>
            {isReceiving
              ? `STREAM: ${useMjpegFallback ? "MJPEG (25 FPS)" : "LIVE (25 FPS)"}`
              : `CHANNEL: ${cameraUid.toUpperCase()}`}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function LiveCameraPlayer(props: LiveCameraPlayerProps) {
  return <LiveCameraPlayerInternal key={props.cameraUid} {...props} />;
}
