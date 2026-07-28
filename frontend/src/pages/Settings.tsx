import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, putHomeboxSettings } from "../api/client";
import { Pending } from "../components/ui/Pending";
import { TextInput } from "../components/ui/inputs";
import { errorText, fieldLabelText, helpText, panel, panelHeading, primaryButtonClass, typeHeading } from "../components/ui/styles";
import { HOMEBOX_SETTINGS_QUERY_KEY, useHomeboxSettingsQuery } from "../hooks/useHomeboxSettings";
import { useRuntimeSettings } from "../hooks/useRuntimeSettings";

const ENV_TAG = (
  <span className="ml-1.5 rounded border border-deck-700 px-1 py-0.5 font-condensed text-[9px] uppercase tracking-wide text-deck-400">
    env
  </span>
);

function EnvRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-deck-800 py-1.5 text-[13px] last:border-b-0">
      <span className="flex items-center text-deck-400">
        {label}
        {ENV_TAG}
      </span>
      <span className="font-mono text-deck-200">{children}</span>
    </div>
  );
}

/** The Settings page (task 4.2): the editable `qr_base_url` setting (the
 * one thing an operator can actually change from the UI, PUT
 * /api/homebox/settings) plus a read-only view of everything else that's
 * only configurable via the environment -- so an operator can SEE what's
 * set without shelling into the container. */
export function Settings() {
  const queryClient = useQueryClient();
  const settingsQuery = useHomeboxSettingsQuery();
  const runtimeQuery = useRuntimeSettings();

  const [qrBaseUrl, setQrBaseUrl] = useState("");
  const [initialized, setInitialized] = useState(false);

  // Sync the form's local buffer from the server value exactly once, the
  // first time it arrives -- same "don't clobber an in-progress edit on an
  // unrelated re-render" reasoning as ui/inputs.tsx's NumberInput.
  useEffect(() => {
    if (settingsQuery.data && !initialized) {
      setQrBaseUrl(settingsQuery.data.qr_base_url ?? "");
      setInitialized(true);
    }
  }, [settingsQuery.data, initialized]);

  const saveMutation = useMutation({
    mutationFn: (value: string | null) => putHomeboxSettings({ qr_base_url: value }),
    onSuccess: (data) => {
      setQrBaseUrl(data.qr_base_url ?? "");
      queryClient.setQueryData(HOMEBOX_SETTINGS_QUERY_KEY, data);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = qrBaseUrl.trim();
    saveMutation.mutate(trimmed === "" ? null : trimmed);
  }

  function handleClear() {
    setQrBaseUrl("");
    saveMutation.mutate(null);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <h1 className={typeHeading}>Settings</h1>

      <section className={panel}>
        <h2 className={panelHeading}>QR base URL</h2>
        {settingsQuery.isPending ? (
          <Pending />
        ) : settingsQuery.isError || !settingsQuery.data ? (
          <p role="alert" className={errorText}>
            Could not load HomeBox settings.
          </p>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
            <p className={helpText}>
              The base URL embedded in printed QR codes for HomeBox labels (e.g. https://homebox.example.com/item or
              .../a/&lt;assetId&gt;). Leave blank to fall back to this app&apos;s own <code className="font-mono text-deck-200">HOMEBOX_URL</code>.
            </p>
            <div>
              <label htmlFor="qr-base-url" className={`${fieldLabelText} mb-1 block`}>
                QR base URL
              </label>
              <TextInput
                id="qr-base-url"
                value={qrBaseUrl}
                onChange={(value) => {
                  setQrBaseUrl(value);
                  saveMutation.reset();
                }}
                placeholder="https://homebox.example.com"
                maxLength={255}
              />
              <p className={helpText}>
                Effective value right now:{" "}
                <span className="font-mono text-deck-200">{settingsQuery.data.effective_qr_base_url ?? "none configured"}</span>
              </p>
            </div>

            {saveMutation.isError && (
              <p role="alert" className={errorText}>
                {saveMutation.error instanceof ApiError ? saveMutation.error.message : "Could not save settings."}
              </p>
            )}
            {saveMutation.isSuccess && (
              <p role="status" className="text-[13px] text-sage-400">
                Saved.
              </p>
            )}

            <div className="flex gap-3">
              <button type="submit" disabled={saveMutation.isPending} className={primaryButtonClass}>
                {saveMutation.isPending ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={handleClear}
                disabled={saveMutation.isPending}
                className="rounded-md border border-deck-600 bg-deck-800 px-4 py-2 text-[13px] font-medium text-deck-200 hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Clear (use fallback)
              </button>
            </div>
          </form>
        )}
      </section>

      <section className={panel}>
        <h2 className={panelHeading}>Runtime configuration</h2>
        <p className={helpText}>Every row below is set via the environment -- change it there and restart the app, not here.</p>
        {runtimeQuery.isPending ? (
          <Pending />
        ) : runtimeQuery.isError || !runtimeQuery.data ? (
          <p role="alert" className={errorText}>
            Could not load runtime configuration.
          </p>
        ) : (
          <div className="mt-3">
            <EnvRow label="Printer mode">{runtimeQuery.data.printer_mode}</EnvRow>
            <EnvRow label="Init strategy">{runtimeQuery.data.printer_init_strategy}</EnvRow>
            <EnvRow label="Bit order">{runtimeQuery.data.printer_bit_order}</EnvRow>
            <EnvRow label="Flip pins">{runtimeQuery.data.printer_flip_pins ? "yes" : "no"}</EnvRow>
            <EnvRow label="ELS enabled">{runtimeQuery.data.els_enabled ? "yes" : "no"}</EnvRow>
            <EnvRow label="ELS tape width">{runtimeQuery.data.els_tape_mm} mm</EnvRow>
            <EnvRow label="Auth mode">{runtimeQuery.data.auth_mode}</EnvRow>
            <EnvRow label="HomeBox configured">{runtimeQuery.data.homebox_configured ? "yes" : "no"}</EnvRow>
          </div>
        )}
      </section>
    </div>
  );
}
