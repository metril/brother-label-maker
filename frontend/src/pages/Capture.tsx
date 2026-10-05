import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ApiError, extractErrorDetail, getHomeboxAssetMatches, getHomeboxEntityPath } from "../api/client";
import type { HomeboxEntitySummary } from "../api/types";
import { useAttachPhoto } from "../hooks/useAttachPhoto";
import { useHomeboxEntities } from "../hooks/useHomeboxEntities";
import { useHomeboxSettingsQuery } from "../hooks/useHomeboxSettings";
import { useSettingsQuery } from "../hooks/useSettings";
import { decodeImageFile, useQrScanner } from "../hooks/useQrScanner";
import { normalizeAssetId, parseScan } from "../lib/assetRef";
import type { ScanRef } from "../lib/assetRef";
import { buildBreadcrumb } from "../lib/homebox";
import { iconButtonClass } from "../components/ui/styles";

/** Phone "Capture" page (route /capture, rendered OUTSIDE AppShell so it is
 * a full-bleed native-feeling screen): scan a printed label's QR (or type
 * its asset number) -> resolve the HomeBox item -> take a photo with the
 * native camera -> upload it as an attachment -> auto-return to scanning. */

type Phase = "scan" | "resolving" | "pick" | "item" | "review" | "uploading" | "done";
type Problem =
  | { kind: "info" | "notfound"; message: string }
  | { kind: "auth" | "forbidden"; message: string }
  | { kind: "retry"; message: string };

const DONE_RETURN_MS = 1200;

const primaryBtn =
  "flex min-h-14 w-full items-center justify-center rounded-xl bg-amber-500 px-5 text-[17px] font-semibold text-on-accent transition active:scale-[0.98] active:bg-amber-300 disabled:opacity-50";
const secondaryBtn =
  "flex min-h-14 w-full items-center justify-center rounded-xl border border-deck-600 bg-deck-800 px-5 text-[16px] font-medium text-deck-200 transition active:scale-[0.98] active:bg-deck-700 disabled:opacity-50";

async function fetchEntity(id: string): Promise<HomeboxEntitySummary> {
  const res = await fetch(`/api/homebox/entities/${encodeURIComponent(id)}`);
  if (!res.ok) {
    const fallback = `request failed: ${res.status} ${res.statusText}`;
    const body: unknown = await res.json().catch(() => null);
    throw new ApiError(res.status, extractErrorDetail(body, fallback));
  }
  return (await res.json()) as HomeboxEntitySummary;
}

function toProblem(err: unknown): Problem {
  if (err instanceof ApiError) {
    if (err.status === 401) return { kind: "auth", message: "Sign in to continue." };
    if (err.status === 404) return { kind: "notfound", message: "Not found in HomeBox." };
    if (err.status === 403) return { kind: "forbidden", message: "Enable HomeBox writes in Settings." };
    return { kind: "retry", message: "HomeBox is unreachable right now." };
  }
  return { kind: "retry", message: "You appear to be offline." };
}

function ProblemBanner({ problem, onRetry }: { problem: Problem; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-rust-500 bg-deck-800 px-4 py-3 text-[15px]">
      <p>{problem.message}</p>
      {problem.kind === "auth" && (
        <a href="/api/auth/login?next=/capture" className="mt-2 inline-block font-semibold text-amber-300 underline">
          Sign in
        </a>
      )}
      {problem.kind === "forbidden" && (
        <Link to="/settings" className="mt-2 inline-block font-semibold text-amber-300 underline">
          Open Settings
        </Link>
      )}
      {problem.kind === "retry" && onRetry && (
        <button type="button" onClick={onRetry} className="mt-2 font-semibold text-amber-300 underline">
          Retry
        </button>
      )}
    </div>
  );
}

export function Capture() {
  const [phase, setPhase] = useState<Phase>("scan");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [candidates, setCandidates] = useState<HomeboxEntitySummary[]>([]);
  const [item, setItem] = useState<HomeboxEntitySummary | null>(null);
  const [asset, setAsset] = useState("");
  const [primary, setPrimary] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const scanFileInput = useRef<HTMLInputElement>(null);
  const lastRef = useRef<ScanRef | null>(null);
  const busy = useRef(false);
  const navigate = useNavigate();
  const [debouncedAsset, setDebouncedAsset] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedAsset(asset.trim()), 250);
    return () => window.clearTimeout(t);
  }, [asset]);

  const settings = useHomeboxSettingsQuery();
  const qrBase = settings.data?.effective_qr_base_url ?? null;
  const appSettings = useSettingsQuery();
  const writesDisabled =
    appSettings.data !== undefined &&
    appSettings.data.settings.find((row) => row.key === "homebox_writes_enabled")?.value !== true;
  const searchTerm = debouncedAsset.length >= 2 && asset.trim() === debouncedAsset ? debouncedAsset : "";
  const search = useHomeboxEntities({ q: searchTerm, page: 1, pageSize: 20, enabled: searchTerm.length >= 2 });
  const searching = asset.trim().length >= 2 && (searchTerm === "" || search.isFetching);
  const results = searchTerm && !search.isPlaceholderData ? search.data?.items ?? [] : [];
  const upload = useAttachPhoto();
  const resetUpload = upload.reset;

  // Native feel: no rubber-banding of the document behind the fixed screen.
  useEffect(() => {
    const el = document.documentElement;
    const prev = el.style.overscrollBehavior;
    el.style.overscrollBehavior = "none";
    return () => {
      el.style.overscrollBehavior = prev;
    };
  }, []);

  const previewUrl = useMemo(
    () => (file && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null),
    [file],
  );
  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const backToScan = useCallback(() => {
    setItem(null);
    setFile(null);
    setCandidates([]);
    setProblem(null);
    resetUpload();
    setAsset("");
    setDebouncedAsset("");
    busy.current = false;
    setPhase("scan");
  }, [resetUpload]);

  const chooseItem = useCallback((entity: HomeboxEntitySummary) => {
    setItem(entity);
    setPrimary(!entity.image_id);
    setProblem(null);
    setPhase("item");
  }, []);

  const resolve = useCallback(
    async (ref: ScanRef) => {
      lastRef.current = ref;
      busy.current = true;
      setProblem(null);
      setPhase("resolving");
      try {
        const matches = ref.kind === "asset" ? await getHomeboxAssetMatches(ref.value) : [await fetchEntity(ref.value)];
        if (matches.length === 0) {
          setProblem({ kind: "notfound", message: `Not found: asset ${ref.value}.` });
          busy.current = false;
          setPhase("scan");
        } else if (matches.length === 1) {
          busy.current = false;
          chooseItem(matches[0]);
        } else {
          busy.current = false;
          setCandidates(matches);
          setPhase("pick");
        }
      } catch (err) {
        setProblem(toProblem(err));
        busy.current = false;
        setPhase("scan");
      }
    },
    [chooseItem],
  );

  const handleText = useCallback(
    (text: string) => {
      if (busy.current) return;
      const ref = parseScan(text, qrBase);
      if (!ref) {
        setProblem({ kind: "info", message: "That QR code isn't a HomeBox label." });
        return;
      }
      void resolve(ref);
    },
    [qrBase, resolve],
  );

  const scanner = useQrScanner({ enabled: phase === "scan", onDetect: handleText });
  const cameraOff = scanner.status === "unavailable" || scanner.status === "denied" || scanner.status === "error";

  useEffect(() => {
    if (phase !== "done") return;
    const t = window.setTimeout(backToScan, DONE_RETURN_MS);
    return () => window.clearTimeout(t);
  }, [phase, backToScan]);

  const pathQuery = useQuery({
    queryKey: ["homebox-entity-path", item?.id],
    queryFn: () => getHomeboxEntityPath(item!.id),
    enabled: item !== null,
  });
  const breadcrumb = pathQuery.data ? buildBreadcrumb(pathQuery.data) : item?.parent?.name ?? "";

  function closeCapture() {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (typeof idx === "number" && idx > 0) navigate(-1);
    else navigate("/homebox");
  }

  function onAssetSubmit(e: FormEvent) {
    e.preventDefault();
    const id = normalizeAssetId(asset);
    if (!id) {
      setProblem({ kind: "info", message: "Enter an asset number (e.g. 123 or 000-123) or pick an item below." });
      return;
    }
    setAsset("");
    void resolve({ kind: "asset", value: id });
  }

  async function onScanFile(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    e.target.value = "";
    if (!picked) return;
    const text = await decodeImageFile(picked);
    if (text) handleText(text);
    else setProblem({ kind: "info", message: "No QR code found in that photo." });
  }

  function onPhoto(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    e.target.value = "";
    if (!picked) return;
    upload.reset();
    setFile(picked);
    setPhase("review");
  }

  function doUpload() {
    if (!item || !file) return;
    setPhase("uploading");
    upload.attach(
      { entityId: item.id, file, primary },
      { onSuccess: () => setPhase("done"), onError: () => setPhase("review") },
    );
  }

  const uploadProblem: Problem | null = upload.error
    ? upload.error.kind === "unauthorized"
      ? { kind: "auth", message: "Sign in to upload." }
      : upload.error.kind === "forbidden"
        ? { kind: "forbidden", message: "Enable HomeBox writes in Settings." }
        : upload.error.kind === "too_large"
          ? { kind: "info", message: "Photo is too large for the server." }
          : upload.error.kind === "bad_type"
            ? { kind: "info", message: "The server rejected this image type." }
            : { kind: "retry", message: upload.error.kind === "offline" ? "You appear to be offline." : "Upload failed." }
    : null;

  return (
    <div
      className="fixed inset-0 flex h-dvh touch-manipulation select-none flex-col overflow-hidden bg-deck-950 text-deck-200 [-webkit-tap-highlight-color:transparent]"
      style={{
        paddingTop: "env(safe-area-inset-top)",
        paddingLeft: "env(safe-area-inset-left)",
        paddingRight: "env(safe-area-inset-right)",
      }}
    >
      <header className="flex min-h-14 shrink-0 items-center justify-between border-b border-deck-700 bg-deck-900 pl-4 pr-2">
        <span className="text-[17px] font-semibold">Capture</span>
        <button
          type="button"
          aria-label="Close capture"
          onClick={closeCapture}
          className={`${iconButtonClass} !h-11 !w-11 min-h-11 min-w-11 text-[24px] leading-none`}
        >
          ×
        </button>
      </header>
      <input
        ref={photoInput}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        aria-label="Take photo"
        data-testid="photo-input"
        onChange={onPhoto}
      />
      <input
        ref={scanFileInput}
        type="file"
        accept="image/*"
        className="hidden"
        aria-label="Scan from photo file"
        data-testid="scan-file-input"
        onChange={(e) => void onScanFile(e)}
      />

      {phase === "scan" && (
        <>
          <div className="relative min-h-0 flex-1 overflow-hidden bg-black">
            {!cameraOff && (
              <video ref={scanner.videoRef} playsInline muted autoPlay className="absolute inset-0 h-full w-full object-cover" />
            )}
            {!cameraOff && (
              <div aria-hidden className="absolute inset-0 flex items-center justify-center">
                <div className="aspect-square w-[62%] max-w-xs rounded-3xl border-2 border-amber-500 shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]" />
              </div>
            )}
            {cameraOff && (
              <p className="absolute inset-x-6 top-1/3 text-center text-[15px] text-deck-400">
                {scanner.status === "denied"
                  ? "Camera access was denied. Enter the asset number or scan from a photo."
                  : "Live scanning needs camera access over HTTPS. Enter the asset number or scan from a photo."}
              </p>
            )}
          </div>
          <div
            className="flex flex-col gap-3 bg-deck-900 px-4 pt-4"
            style={{ paddingBottom: "max(env(safe-area-inset-bottom), 16px)" }}
          >
            {problem && <ProblemBanner problem={problem} onRetry={() => lastRef.current && void resolve(lastRef.current)} />}
            <form onSubmit={onAssetSubmit} className="flex gap-2">
              <input
                type="text"
                enterKeyHint="go"
                autoComplete="off"
                autoCapitalize="none"
                placeholder="Asset # or item name"
                aria-label="Find item"
                value={asset}
                onChange={(e) => setAsset(e.target.value)}
                className="min-h-14 min-w-0 flex-1 select-text rounded-xl border border-deck-600 bg-deck-800 px-4 text-[16px] text-deck-200 placeholder:text-deck-400"
              />
              <button type="submit" className="min-h-14 rounded-xl bg-amber-500 px-6 text-[17px] font-semibold text-on-accent active:bg-amber-300">
                Go
              </button>
            </form>
            {asset.trim().length >= 2 && (
              <div className="max-h-[30dvh] overflow-y-auto" aria-label="Search results">
                {searching && results.length === 0 ? (
                  <p role="status" className="px-1 py-2 text-[15px] text-deck-400">
                    Searching…
                  </p>
                ) : search.isError ? (
                  <p role="alert" className="px-1 py-2 text-[15px] text-deck-400">
                    Search failed. Check your connection.
                  </p>
                ) : results.length === 0 ? (
                  <p className="px-1 py-2 text-[15px] text-deck-400">No matches</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {results.map((r) => (
                      <li key={r.id}>
                        <button
                          type="button"
                          onClick={() => chooseItem(r)}
                          className="flex min-h-12 w-full flex-col items-start justify-center rounded-xl border border-deck-600 bg-deck-800 px-4 py-2 text-left active:bg-deck-700"
                        >
                          <span className="text-[16px] text-deck-200">{r.name}</span>
                          {(r.asset_id || r.parent?.name) && (
                            <span className="text-[13px] text-deck-400">
                              {[r.asset_id && `#${r.asset_id}`, r.parent?.name].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <button type="button" className={secondaryBtn} onClick={() => scanFileInput.current?.click()}>
              Scan from photo
            </button>
          </div>
        </>
      )}

      {phase === "resolving" && (
        <div className="flex flex-1 items-center justify-center text-[17px] text-deck-400" role="status">
          Looking up item…
        </div>
      )}

      {phase === "pick" && (
        <Screen>
          <h1 className="text-[20px] font-semibold">Which item?</h1>
          <ul className="flex flex-col gap-2">
            {candidates.map((c) => (
              <li key={c.id}>
                <button type="button" className={secondaryBtn} onClick={() => chooseItem(c)}>
                  {c.name} · {c.asset_id}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className={`${secondaryBtn} mt-auto`} onClick={backToScan}>
            Back to scanning
          </button>
        </Screen>
      )}

      {phase === "item" && item && (
        <Screen>
          <div className="rounded-2xl border border-deck-600 bg-deck-900 p-4">
            <h1 className="text-[22px] font-semibold leading-tight">{item.name}</h1>
            {item.asset_id && <p className="mt-1 text-[14px] text-deck-400">#{item.asset_id}</p>}
            {breadcrumb && <p className="mt-1 text-[14px] text-deck-400">{breadcrumb}</p>}
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={primary}
            onClick={() => setPrimary((p) => !p)}
            className="flex min-h-14 items-center justify-between rounded-xl border border-deck-600 bg-deck-800 px-4 text-[16px] active:bg-deck-700"
          >
            <span>Set as primary</span>
            <span className={`rounded-full px-3 py-1 text-[14px] font-semibold ${primary ? "bg-amber-500 text-on-accent" : "bg-deck-700 text-deck-400"}`}>
              {primary ? "On" : "Off"}
            </span>
          </button>
          {writesDisabled && <ProblemBanner problem={{ kind: "forbidden", message: "Enable HomeBox writes in Settings." }} />}
          <div className="mt-auto flex flex-col gap-3">
            <button type="button" className={primaryBtn} disabled={writesDisabled} onClick={() => photoInput.current?.click()}>
              Take photo
            </button>
            <button type="button" className={secondaryBtn} onClick={backToScan}>
              Scan another
            </button>
          </div>
        </Screen>
      )}

      {(phase === "review" || phase === "uploading") && item && (
        <Screen>
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-2xl bg-black">
            {previewUrl ? (
              <img src={previewUrl} alt="Photo preview" className="max-h-full max-w-full object-contain" />
            ) : (
              <p className="text-deck-400">{file?.name}</p>
            )}
          </div>
          {phase === "uploading" ? (
            <div role="status" className="flex flex-col gap-2">
              <p className="text-[16px]">Uploading… {Math.round(upload.progress * 100)}%</p>
              <progress value={upload.progress} max={1} className="h-2 w-full accent-amber-500" />
            </div>
          ) : (
            <>
              {uploadProblem && <ProblemBanner problem={uploadProblem} onRetry={doUpload} />}
              <div className="flex gap-3">
                <button type="button" className={secondaryBtn} onClick={() => photoInput.current?.click()}>
                  Retake
                </button>
                <button type="button" className={primaryBtn} onClick={doUpload}>
                  Upload
                </button>
              </div>
            </>
          )}
        </Screen>
      )}

      {phase === "done" && item && (
        <Screen>
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center" role="status">
            <div className="flex h-24 w-24 items-center justify-center rounded-full bg-sage-400 text-5xl text-on-accent motion-safe:animate-pulse">
              ✓
            </div>
            <p className="text-[20px] font-semibold">Saved to {item.name}</p>
          </div>
          <button type="button" className={secondaryBtn} onClick={() => setPhase("item")}>
            Add another photo
          </button>
        </Screen>
      )}
    </div>
  );
}

function Screen({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 px-4 pt-4"
      style={{ paddingBottom: "max(env(safe-area-inset-bottom), 16px)" }}
    >
      {children}
    </div>
  );
}
