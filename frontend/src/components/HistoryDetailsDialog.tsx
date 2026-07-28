import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type { RefObject } from "react";
import { getHistoryJob } from "../api/client";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { extractSingleLabel } from "../lib/history";
import { useDesignerStore } from "../stores/designer";
import { Dialog } from "./ui/Dialog";
import { Pending } from "./ui/Pending";
import { eyebrow, iconButtonClass, primaryButtonClass } from "./ui/styles";

interface HistoryDetailsDialogProps {
  jobId: string | null;
  open: boolean;
  onClose: () => void;
  closeButtonRef: RefObject<HTMLButtonElement>;
}

/** History row "Details" (task 2.13's brief): GET /api/history/{id} (the
 * FULL job resource, `definition` included) shown read-only as mono JSON,
 * plus a "Load into designer" button when that definition turns out to be
 * a single, un-serialized label (lib/history.ts's extractSingleLabel --
 * a tray print of several labels or a serialized run has no single
 * "the design" to load). Fetches lazily: `enabled` only while the dialog
 * is actually open, so opening ten rows' worth of details over a session
 * doesn't fire ten requests up front. */
export function HistoryDetailsDialog({ jobId, open, onClose, closeButtonRef }: HistoryDetailsDialogProps) {
  const navigate = useNavigate();
  const { data: labelTypes } = useLabelTypes();
  const selectType = useDesignerStore((s) => s.selectType);
  const setParams = useDesignerStore((s) => s.setParams);
  const setTapeWidthMm = useDesignerStore((s) => s.setTapeWidthMm);
  const setTapeFamily = useDesignerStore((s) => s.setTapeFamily);

  const { data: job, isPending } = useQuery({
    queryKey: ["history-detail", jobId],
    queryFn: () => getHistoryJob(jobId as string),
    enabled: open && jobId !== null,
  });

  const singleLabel = job ? extractSingleLabel(job.definition) : null;
  const typeInfo = singleLabel ? labelTypes?.find((t) => t.type === singleLabel.type) : null;

  function handleLoad() {
    if (!singleLabel || !typeInfo) return;
    selectType(singleLabel.type, typeInfo.params_schema);
    setParams(singleLabel.type, singleLabel.params);
    setTapeFamily(singleLabel.tape.family);
    setTapeWidthMm(singleLabel.tape.width_mm);
    onClose();
    navigate("/");
  }

  return (
    <Dialog open={open} onClose={onClose} label="Job details" className="max-w-2xl">
      <div className="flex items-center justify-between gap-2">
        <span className={eyebrow}>Job details</span>
        <button type="button" ref={closeButtonRef} onClick={onClose} aria-label="Close job details" className={iconButtonClass}>
          ×
        </button>
      </div>
      {isPending || !job ? (
        <div className="mt-4">
          <Pending />
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          <pre className="max-h-96 overflow-auto rounded-md border border-deck-700 bg-deck-950 p-3 font-mono text-[11px] leading-snug text-deck-200">
            {JSON.stringify(job.definition, null, 2)}
          </pre>
          {singleLabel && typeInfo && (
            <button type="button" onClick={handleLoad} className={`${primaryButtonClass} self-start`}>
              Load into designer
            </button>
          )}
        </div>
      )}
    </Dialog>
  );
}
