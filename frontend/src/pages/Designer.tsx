import {
  buildDefinition,
  hasRenderableContent,
  tapeMismatchWarning,
  useDesignerStore,
} from "../stores/designer";
import { usePreview } from "../hooks/usePreview";
import { usePrinterStatus } from "../hooks/usePrinterStatus";
import { TapeSelector } from "../components/TapeSelector";
import { TextLabelForm } from "../components/TextLabelForm";
import { LabelPreview } from "../components/LabelPreview";
import { PrintButton } from "../components/PrintButton";

const panel = "rounded-xl border border-ink-800 bg-ink-900/40 p-6";
const panelHeading = "mb-4 text-sm font-semibold uppercase tracking-wide text-ink-400";

export function Designer() {
  const tape = useDesignerStore((s) => s.tape);
  const params = useDesignerStore((s) => s.params);
  const setTapeWidthMm = useDesignerStore((s) => s.setTapeWidthMm);

  const hasContent = hasRenderableContent(params);
  const definition = buildDefinition(tape, params);
  const preview = usePreview(definition);

  // I1: preflight guardrail (not a hard block -- see tapeMismatchWarning's
  // docstring for why printing itself stays enabled on a mismatch).
  const printerStatus = usePrinterStatus();
  const tapeWarning = tapeMismatchWarning(
    tape.width_mm,
    printerStatus.data?.connected ?? false,
    printerStatus.data?.status?.media_width_mm,
  );

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 lg:flex-row lg:items-start">
      <section className={`${panel} flex-1`}>
        <h2 className={panelHeading}>Text label</h2>
        {tapeWarning && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-amber-600/50 bg-amber-950 px-3 py-2 text-xs text-amber-300"
          >
            {tapeWarning}
          </div>
        )}
        <div className="mb-6">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-400">
            Tape
          </span>
          <TapeSelector valueMm={tape.width_mm} onChange={setTapeWidthMm} />
        </div>
        <TextLabelForm />
      </section>

      <section className="flex w-full flex-col gap-6 lg:w-96">
        <div className={panel}>
          <h2 className={panelHeading}>Preview</h2>
          <LabelPreview
            tapeWidthMm={tape.width_mm}
            hasContent={hasContent}
            png={preview.png}
            lengthMm={preview.lengthMm}
            warnings={preview.warnings}
            isFetching={preview.isFetching}
            error={preview.error}
          />
        </div>
        <PrintButton definition={definition} disabled={!hasContent} />
        {tapeWarning && <p className="text-xs text-amber-400">{tapeWarning}</p>}
      </section>
    </div>
  );
}
