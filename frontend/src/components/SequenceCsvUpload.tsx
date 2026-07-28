import { useMutation } from "@tanstack/react-query";
import { ApiError, postSerializeCsv } from "../api/client";
import { csvColumns } from "../lib/sequence";
import { Pending } from "./ui/Pending";
import { errorText, fieldLabelText, helpText } from "./ui/styles";
import type { Sequence } from "../api/types";

const PREVIEW_ROW_COUNT = 5;

interface SequenceCsvUploadProps {
  sequence: Sequence;
  onPatch: (partial: Partial<Sequence>) => void;
}

/** CSV-kind Sequence editing (task 2.11): POST /api/serialize/csv -> show
 * the detected columns (as `{csv.<col>}` reference chips -- the actual
 * INSERT affordance lives per-text-field, see schema/TokenInsertButtons.
 * tsx), a row count, and a first-5-rows preview table, mono and
 * horizontally scrollable per the brief. Errors (ragged/empty/dup-header/
 * too many rows) are the backend's own readable HTTPException(422,
 * detail=...) strings, surfaced verbatim -- see router_labels.py's
 * upload_serialize_csv. */
export function SequenceCsvUpload({ sequence, onPatch }: SequenceCsvUploadProps) {
  const upload = useMutation({
    mutationFn: postSerializeCsv,
    onSuccess: (result) => onPatch({ rows: result.rows }),
  });

  const rows = sequence.rows ?? [];
  const columns = csvColumns(rows);

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="sequence-csv-file" className={`${fieldLabelText} mb-1 block`}>
        CSV file
      </label>
      <input
        id="sequence-csv-file"
        type="file"
        accept=".csv,text/csv"
        aria-label="Upload CSV"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
        className="text-[12px] text-deck-400 file:mr-3 file:rounded-md file:border file:border-deck-600 file:bg-deck-800 file:px-3 file:py-1.5 file:text-deck-200"
      />
      {upload.isPending && <Pending />}
      {upload.isError && (
        <p role="alert" className={errorText}>
          {upload.error instanceof ApiError ? upload.error.message : "CSV upload failed"}
        </p>
      )}

      {rows.length === 0 ? (
        <p className={helpText}>
          Upload a CSV to drive this run from its rows -- each column becomes a {"{csv.<column>}"} token you can
          insert into any text field.
        </p>
      ) : (
        <>
          <p className="font-mono text-[13px] text-deck-200">
            {rows.length} row{rows.length === 1 ? "" : "s"}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {columns.map((column) => (
              <span
                key={column}
                className="rounded-full border border-deck-600 bg-deck-800 px-2 py-0.5 font-mono text-[11px] text-deck-400"
              >
                {`{csv.${column}}`}
              </span>
            ))}
          </div>
          <div className="overflow-x-auto rounded-md border border-deck-700">
            <table className="min-w-full font-mono text-[12px]">
              <thead>
                <tr className="border-b border-deck-700 bg-deck-800/60">
                  {columns.map((column) => (
                    <th key={column} className="whitespace-nowrap px-2 py-1 text-left text-deck-400">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, PREVIEW_ROW_COUNT).map((row, i) => (
                  <tr key={i} className="border-b border-deck-800 last:border-0">
                    {columns.map((column) => (
                      <td key={column} className="whitespace-nowrap px-2 py-1 text-deck-200">
                        {row[column]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > PREVIEW_ROW_COUNT && (
            <p className={helpText}>… and {rows.length - PREVIEW_ROW_COUNT} more rows.</p>
          )}
        </>
      )}
    </div>
  );
}
