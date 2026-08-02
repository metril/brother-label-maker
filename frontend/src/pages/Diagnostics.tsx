import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { KeepAliveStatus } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { Pending } from "../components/ui/Pending";
import { errorText, eyebrow, fieldLabelText, panel, panelHeading, typeHeading } from "../components/ui/styles";
import { useAuth } from "../hooks/useAuth";
import { useHealth } from "../hooks/useHealth";
import { useHistoryList } from "../hooks/useHistory";
import { useHomeboxStatus } from "../hooks/useHomeboxStatus";
import { useJobEventsContext } from "../hooks/useJobEvents";
import { usePrinterStatus } from "../hooks/usePrinterStatus";
import { formatAbsoluteTime, formatRelativeTime } from "../lib/time";
import { buildRawMediaReport, describeMedia, describeMediaTypeRaw } from "../lib/printerStatus";

const RECENT_JOBS_COUNT = 5;
const COPIED_MESSAGE_MS = 2000;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-deck-800 py-1.5 text-[13px] last:border-b-0">
      <span className="text-deck-400">{label}</span>
      <span className="font-mono text-deck-200">{children}</span>
    </div>
  );
}

/** `null` renders as "—" (unknown/not-yet-loaded), distinct from an actual
 * false -- e.g. HomeboxStatus's reachable/healthy are null together only
 * while `configured` is false (see that type's own doc), and a page still
 * loading its own reachability probe shouldn't read as a hard "no" either. */
function BoolValue({ value }: { value: boolean | null }) {
  if (value == null) return <span className="text-deck-400">—</span>;
  return <span className={value ? "text-sage-400" : "text-rust-500"}>{value ? "yes" : "no"}</span>;
}

/** commit 6: a readable label for the keep-awake poller's last attempt --
 * `null` covers both "never enabled" and "enabled but hasn't attempted a
 * poll yet" (see KeepAliveStatus's own doc in api/types.ts). */
function keepAliveResultText(result: KeepAliveStatus["last_result"]): string {
  switch (result) {
    case "ok":
      return "OK";
    case "skipped_busy":
      return "Skipped (printer busy)";
    case "error":
      return "Error";
    default:
      return "—";
  }
}

/** The keep-awake poller's own row group inside the Printer section
 * (task/commit 6) -- enabled/disabled, when it last attempted a poll (if
 * ever), and that attempt's outcome. Shown regardless of `connected`/
 * `status` (the poller's own state is independent of whether THIS request
 * could reach the printer). */
function KeepAliveRows({ keepAlive }: { keepAlive: KeepAliveStatus }) {
  return (
    <div>
      <Row label="Keep-awake">
        <BoolValue value={keepAlive.enabled} />
      </Row>
      <Row label="Last poll">
        {keepAlive.last_attempt_at ? (
          <time dateTime={keepAlive.last_attempt_at} title={formatAbsoluteTime(keepAlive.last_attempt_at)}>
            {formatRelativeTime(keepAlive.last_attempt_at)}
          </time>
        ) : (
          "never"
        )}
      </Row>
      <Row label="Last result">{keepAliveResultText(keepAlive.last_result)}</Row>
      {keepAlive.last_error && (
        <p role="alert" className={`${errorText} mt-2`}>
          {keepAlive.last_error}
        </p>
      )}
    </div>
  );
}

/** The Diagnostics page (task 4.2): one screen an operator opens when
 * something is off. Four sections, each independently loading/failing
 * (its own isPending/isError branch) so one slow/broken probe never blanks
 * the other three: Printer (with the media-observation block handoff §7
 * asks for -- the raw status bytes alongside their decoded interpretation,
 * explicit about anything this app doesn't recognize), HomeBox, App
 * (health/version/auth mode/WS stream), and a Print worker summary linking
 * to the full History page. */
export function Diagnostics() {
  const printer = usePrinterStatus();
  const homebox = useHomeboxStatus();
  const health = useHealth();
  const auth = useAuth();
  const { connectionState } = useJobEventsContext();
  const recentJobs = useHistoryList({ page: 1, pageSize: RECENT_JOBS_COUNT });

  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  async function copyRawBlock(text: string) {
    // navigator.clipboard is [SecureContext]-gated: on plain-http LAN --
    // this app's documented baseline, and the exact place this page gets
    // used against real hardware -- the property is simply undefined. A
    // silent no-op here would leave an operator pasting stale clipboard
    // contents into protocol-notes.md (review); say it out loud instead.
    if (!navigator.clipboard) {
      setCopyFailed(true);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyFailed(false);
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MESSAGE_MS);
    } catch {
      setCopyFailed(true);
    }
  }

  const status = printer.data?.status ?? null;
  const backendReachable = health.isPending ? null : !health.isError;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <h1 className={typeHeading}>Diagnostics</h1>

      <section className={panel}>
        <h2 className={panelHeading}>Printer</h2>
        {printer.isPending ? (
          <Pending />
        ) : printer.isError || !printer.data ? (
          <p role="alert" className={errorText}>
            Could not load printer status.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <div>
              <Row label="Mode">{printer.data.printer_mode}</Row>
              <Row label="Connected">
                <BoolValue value={printer.data.connected} />
              </Row>
            </div>
            <KeepAliveRows keepAlive={printer.data.keep_alive} />
            {printer.data.error && (
              <p role="alert" className={errorText}>
                {printer.data.error}
              </p>
            )}

            {status && (
              <>
                <Row label="Detected tape">{describeMedia(status) ?? "—"}</Row>

                {status.has_error && (
                  <div>
                    <p className={fieldLabelText}>Printer-reported errors</p>
                    <ul className="mt-1 list-disc pl-5 text-[13px] text-rust-500">
                      {status.errors.map((message, i) => (
                        <li key={`${message}-${i}`}>{message}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="rounded-lg border border-deck-700 bg-deck-950/40 p-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <p className={eyebrow}>Raw status block (media observation)</p>
                    <button
                      type="button"
                      onClick={() => void copyRawBlock(buildRawMediaReport(status))}
                      className="rounded-md border border-deck-600 px-2 py-1 font-condensed text-[11px] font-medium uppercase tracking-wide text-deck-200 hover:border-deck-400"
                    >
                      Copy raw block
                    </button>
                  </div>
                  <p className="break-all font-mono text-[12px] text-deck-200">{status.raw_hex}</p>
                  <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[12px]">
                    <dt className="text-deck-400">byte10 media_width_mm</dt>
                    <dd className="font-mono text-deck-200">
                      {status.media_width_mm} (0x{status.media_width_mm.toString(16).padStart(2, "0")})
                    </dd>
                    <dt className="text-deck-400">byte11 media_type_raw</dt>
                    <dd className="font-mono text-deck-200">{describeMediaTypeRaw(status)}</dd>
                  </dl>
                  {copied && (
                    <p role="status" className="mt-2 text-[12px] text-sage-400">
                      Copied to clipboard.
                    </p>
                  )}
                  {copyFailed && (
                    <p role="alert" className="mt-2 text-[12px] text-amber-300">
                      Copy needs HTTPS (the clipboard API is blocked on plain http) — select
                      the block above and copy it manually.
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </section>

      <section className={panel}>
        <h2 className={panelHeading}>HomeBox</h2>
        {homebox.isPending ? (
          <Pending />
        ) : homebox.isError || !homebox.data ? (
          <p role="alert" className={errorText}>
            Could not load HomeBox status.
          </p>
        ) : (
          <div>
            <Row label="Configured">
              <BoolValue value={homebox.data.configured} />
            </Row>
            <Row label="Reachable">
              <BoolValue value={homebox.data.reachable} />
            </Row>
            <Row label="Healthy">
              <BoolValue value={homebox.data.healthy} />
            </Row>
            <Row label="Version">{homebox.data.version ?? "—"}</Row>
            {homebox.data.error && (
              <p role="alert" className={`${errorText} mt-2`}>
                {homebox.data.error}
              </p>
            )}
          </div>
        )}
      </section>

      <section className={panel}>
        <h2 className={panelHeading}>App</h2>
        <div>
          <Row label="Backend reachable">
            <BoolValue value={backendReachable} />
          </Row>
          <Row label="Backend version">{health.data?.version ?? "—"}</Row>
          <Row label="Printer mode">{health.data?.printer_mode ?? "—"}</Row>
          <Row label="Auth mode">{auth.data?.auth_mode ?? "—"}</Row>
          <Row label="Job event stream">{connectionState}</Row>
        </div>
      </section>

      <section className={panel}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className={`${panelHeading} mb-0`}>Print worker</h2>
          <Link to="/history" className="text-[12px] font-medium text-amber-300 hover:underline">
            View all history
          </Link>
        </div>
        {recentJobs.isPending ? (
          <Pending />
        ) : recentJobs.isError || !recentJobs.data ? (
          <p role="alert" className={errorText}>
            Could not load recent jobs.
          </p>
        ) : recentJobs.data.items.length === 0 ? (
          <p className="text-[13px] text-deck-400">Nothing printed yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {recentJobs.data.items.map((job) => (
              <li key={job.id} className="flex items-center justify-between gap-3 text-[13px]">
                <span className="font-mono text-deck-400">{job.id}</span>
                <StatusChip status={job.status} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
