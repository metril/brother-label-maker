import { useCallback, useEffect, useRef, useState } from "react";

export type ScannerStatus = "idle" | "starting" | "scanning" | "unavailable" | "denied" | "error";

interface Options {
  /** Camera runs only while true; flipping it false stops every track. */
  enabled: boolean;
  /** Called with each decoded QR payload (the same text is debounced for 2s). */
  onDetect: (text: string) => void;
}

const DECODE_INTERVAL_MS = 125; // ~8 fps
const REPEAT_SUPPRESS_MS = 2000;

type Detector = { detect: (src: ImageBitmapSource) => Promise<{ rawValue: string }[]> };

let detectorPromise: Promise<Detector> | null = null;

/** Lazily loads the barcode-detector ponyfill (zxing-wasm underneath) and
 * points zxing-wasm at a Vite-emitted copy of the reader .wasm -- its
 * default `locateFile` fetches from jsDelivr, which a LAN-only appliance
 * must never do. A failed load is not cached, so a retry can succeed. */
function loadDetector(): Promise<Detector> {
  if (!detectorPromise) {
    detectorPromise = (async () => {
      const [{ BarcodeDetector, setZXingModuleOverrides }, wasm] = await Promise.all([
        import("barcode-detector/ponyfill"),
        import("zxing-wasm/reader/zxing_reader.wasm?url"),
      ]);
      const wasmUrl = wasm.default;
      setZXingModuleOverrides({
        locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? wasmUrl : prefix + path),
      });
      return new BarcodeDetector({ formats: ["qr_code"] });
    })().catch((err) => {
      detectorPromise = null;
      throw err;
    });
  }
  return detectorPromise;
}

/** Decodes a QR from a photo file ("Scan from photo" fallback); null when
 * nothing is found or the image can't be decoded. */
export async function decodeImageFile(file: File): Promise<string | null> {
  try {
    const detector = await loadDetector();
    const bitmap = await createImageBitmap(file);
    try {
      const hits = await detector.detect(bitmap);
      return hits[0]?.rawValue ?? null;
    } finally {
      bitmap.close();
    }
  } catch {
    return null;
  }
}

/** Live camera QR scanning. Attach `videoRef` to a <video playsInline muted>.
 * Tracks are stopped on disable, unmount and when the page is hidden. */
export function useQrScanner({ enabled, onDetect }: Options) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<ScannerStatus>("idle");
  // Bumped to re-run the start effect (foreground return, manual restart).
  const [run, setRun] = useState(0);
  const onDetectRef = useRef(onDetect);
  useEffect(() => {
    onDetectRef.current = onDetect;
  }, [onDetect]);

  useEffect(() => {
    if (!enabled) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("unavailable");
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let handle = 0;
    let usedVideoFrame = false;
    let busy = false;
    let last = 0;
    let lastText = "";
    let lastTextAt = 0;

    const stop = () => {
      cancelled = true;
      if (handle) {
        const v = videoRef.current;
        if (usedVideoFrame && v && "cancelVideoFrameCallback" in v) v.cancelVideoFrameCallback(handle);
        else cancelAnimationFrame(handle);
        handle = 0;
      }
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      const v = videoRef.current;
      if (v) v.srcObject = null;
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        stop();
        setStatus("idle");
      } else if (cancelled) {
        setRun((n) => n + 1);
      }
    };

    async function start() {
      setStatus("starting");
      try {
        // Assign the stream BEFORE loading the detector so a failed/slow
        // detector load can never leak a live camera track.
        const media = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        stream = media;
        if (cancelled) {
          stop();
          return;
        }
        const detector = await loadDetector();
        if (cancelled) {
          stop();
          return;
        }
        const video = videoRef.current;
        if (!video) {
          stop();
          return;
        }
        video.muted = true;
        video.setAttribute("playsinline", "");
        video.srcObject = media;
        await video.play();
        if (cancelled) return;
        setStatus("scanning");

        const tick = (now: number) => {
          if (cancelled) return;
          schedule();
          if (busy || now - last < DECODE_INTERVAL_MS || video.readyState < 2) return;
          last = now;
          busy = true;
          detector
            .detect(video)
            .then((hits) => {
              const text = hits[0]?.rawValue;
              if (!text || cancelled) return;
              const t = performance.now();
              if (text === lastText && t - lastTextAt < REPEAT_SUPPRESS_MS) return;
              lastText = text;
              lastTextAt = t;
              onDetectRef.current(text);
            })
            .catch(() => {})
            .finally(() => {
              busy = false;
            });
        };
        const schedule = () => {
          if (typeof video.requestVideoFrameCallback === "function") {
            usedVideoFrame = true;
            handle = video.requestVideoFrameCallback((now) => tick(now));
          } else {
            handle = requestAnimationFrame(tick);
          }
        };
        schedule();
      } catch (err) {
        const wasCancelled = cancelled;
        stop();
        if (wasCancelled) return;
        const name = err instanceof DOMException ? err.name : "";
        setStatus(name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError" ? "denied" : "error");
      }
    }

    document.addEventListener("visibilitychange", onVisibility);
    void start();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [enabled, run]);

  const visibleStatus: ScannerStatus = enabled ? status : "idle";
  const restart = useCallback(() => setRun((n) => n + 1), []);
  return { videoRef, status: visibleStatus, restart };
}
