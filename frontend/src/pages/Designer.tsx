import { buildDefinition, hasRenderableContent, useDesignerStore } from "../stores/designer";
import { usePreview } from "../hooks/usePreview";
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
  const preview = usePreview(definition, hasContent);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 lg:flex-row lg:items-start">
      <section className={`${panel} flex-1`}>
        <h2 className={panelHeading}>Text label</h2>
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
      </section>
    </div>
  );
}
