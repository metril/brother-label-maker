import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, putHomeboxSettings } from "../api/client";
import type { SettingRow, SettingsSource } from "../api/types";
import { Pending } from "../components/ui/Pending";
import { NumberInput, Select, TextInput } from "../components/ui/inputs";
import { Switch } from "../components/ui/Switch";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import {
  errorText,
  fieldLabelText,
  helpText,
  panel,
  panelHeading,
  primaryButtonClass,
  typeHeading,
} from "../components/ui/styles";
import { HOMEBOX_SETTINGS_QUERY_KEY, useHomeboxSettingsQuery } from "../hooks/useHomeboxSettings";
import { useSettingsQuery, useUpdateSettings } from "../hooks/useSettings";

const SECONDARY_BUTTON_CLASS =
  "rounded-md border border-deck-600 bg-deck-800 px-4 py-2 text-[13px] font-medium text-deck-200 hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-60";

const ELS_TAPE_MM_MIN = 3.5;
const ELS_TAPE_MM_MAX = 36;

function findRow(rows: SettingRow[], key: string): SettingRow | undefined {
  return rows.find((row) => row.key === key);
}

/** A small mono tag naming WHERE a setting's current effective value comes
 * from -- `"db"` (an override saved from this page), `"env"` (this app's
 * environment), or `"default"` (the class's own hardcoded fallback).
 * Replaces the old fixed "env" tag every row used to carry unconditionally
 * -- now every editable row can genuinely be any of the three. */
function ProvenanceBadge({ source }: { source: SettingsSource }) {
  return (
    <span className="ml-1.5 rounded border border-deck-700 px-1 py-0.5 font-condensed text-[9px] uppercase tracking-wide text-deck-400">
      {source}
    </span>
  );
}

function ResetToEnvButton({
  onClick,
  disabled,
  label = "Reset to env",
}: {
  onClick: () => void;
  disabled?: boolean;
  /** Defaults to "Reset to env" -- accurate for every field that has a real
   * AppConfig/env tier to fall back to. The two DB-only fields
   * (keep_printer_awake/keep_awake_interval_min, see settings_overlay.py)
   * have no env tier at all -- provenance() for those only ever reports
   * "db" or "default" -- so their own reset buttons pass "Reset to
   * default" instead, since that's genuinely what clicking it does. */
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="text-[11px] font-medium text-deck-400 underline decoration-dotted hover:text-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {label}
    </button>
  );
}

function SettingErrorText({ mutation }: { mutation: ReturnType<typeof useUpdateSettings> }) {
  if (!mutation.isError) return null;
  return (
    <p role="alert" className={errorText}>
      {mutation.error instanceof ApiError ? mutation.error.message : "Could not save this setting."}
    </p>
  );
}

// --- Printer section: three Selects + one Switch, each independently ------
// editable (a change fires PUT /api/settings immediately -- no separate
// Save button, matching Switch's own "takes effect immediately" ethos and
// keeping a fixed, small choice set out of the buffered-text-input pattern
// the URL/number fields below need instead).

interface SelectSettingRowProps {
  label: string;
  fieldKey: string;
  rows: SettingRow[];
  options: { value: string; label: string }[];
}

function SelectSettingRow({ label, fieldKey, rows, options }: SelectSettingRowProps) {
  const row = findRow(rows, fieldKey);
  const mutation = useUpdateSettings();
  const value = typeof row?.value === "string" ? row.value : (options[0]?.value ?? "");

  return (
    <div className="border-b border-deck-800 py-2 text-[13px] last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center text-deck-200">
          {label}
          {row && <ProvenanceBadge source={row.source} />}
        </span>
        <div className="flex items-center gap-2">
          <Select
            value={value}
            onChange={(next) => mutation.mutate({ [fieldKey]: next })}
            options={options}
            ariaLabel={label}
            disabled={mutation.isPending}
          />
          {row?.source === "db" && (
            <ResetToEnvButton onClick={() => mutation.mutate({ [fieldKey]: null })} disabled={mutation.isPending} />
          )}
        </div>
      </div>
      <SettingErrorText mutation={mutation} />
    </div>
  );
}

function SwitchSettingRow({
  label,
  fieldKey,
  rows,
  resetLabel,
  help,
}: {
  label: string;
  fieldKey: string;
  rows: SettingRow[];
  resetLabel?: string;
  help?: string;
}) {
  const row = findRow(rows, fieldKey);
  const mutation = useUpdateSettings();
  const checked = row?.value === true;

  return (
    <div className="border-b border-deck-800 py-2 text-[13px] last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center">
          <Switch
            id={`setting-${fieldKey}`}
            checked={checked}
            onChange={(next) => mutation.mutate({ [fieldKey]: next })}
            label={label}
            disabled={mutation.isPending}
          />
          {row && <ProvenanceBadge source={row.source} />}
        </span>
        {row?.source === "db" && (
          <ResetToEnvButton
            onClick={() => mutation.mutate({ [fieldKey]: null })}
            disabled={mutation.isPending}
            {...(resetLabel ? { label: resetLabel } : {})}
          />
        )}
      </div>
      {help && <p className={helpText}>{help}</p>}
      <SettingErrorText mutation={mutation} />
    </div>
  );
}

const PRINTER_MODE_OPTIONS = [
  { value: "mock", label: "Mock" },
  { value: "usb", label: "USB" },
];
const INIT_STRATEGY_OPTIONS = [
  { value: "classic", label: "Classic" },
  { value: "e310bt", label: "E310BT" },
];
const BIT_ORDER_OPTIONS = [
  { value: "msb_first", label: "MSB first" },
  { value: "lsb_first", label: "LSB first" },
];

// -- keep-awake poller (commit 6): a DB-only Switch + buffered number field,
// no AppConfig/env tier for either (settings_overlay.py's _DB_ONLY_DEFAULTS)
// -- ridden on the same SwitchSettingRow every other boolean setting uses,
// and a KeepAwakeIntervalField mirroring ElsTapeMmField's buffered-number
// pattern below (the only other numeric editable field on this page) since
// a free-typed number needs the same "don't fight the user mid-edit,
// explicit Save" contract NumberInput itself documents.

const KEEP_AWAKE_INTERVAL_MIN_MIN = 1;
const KEEP_AWAKE_INTERVAL_MIN_MAX = 60;

function KeepAwakeIntervalField({ rows }: { rows: SettingRow[] }) {
  const row = findRow(rows, "keep_awake_interval_min");
  const serverValue = typeof row?.value === "number" ? row.value : null;
  const mutation = useUpdateSettings();
  const [value, setValue] = useState<number | undefined>(serverValue ?? undefined);

  useEffect(() => {
    setValue(serverValue ?? undefined);
  }, [serverValue]);

  const outOfRange =
    value === undefined || value < KEEP_AWAKE_INTERVAL_MIN_MIN || value > KEEP_AWAKE_INTERVAL_MIN_MAX;

  function handleSave() {
    if (outOfRange || value === undefined) return;
    mutation.mutate({ keep_awake_interval_min: value });
  }

  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center text-deck-200">
          Keep-awake interval (minutes)
          {row && <ProvenanceBadge source={row.source} />}
        </span>
        {row?.source === "db" && (
          <ResetToEnvButton
            onClick={() => mutation.mutate({ keep_awake_interval_min: null })}
            disabled={mutation.isPending}
            label="Reset to default"
          />
        )}
      </div>
      <div className="flex items-center gap-2">
        <NumberInput
          value={value}
          onChange={setValue}
          min={KEEP_AWAKE_INTERVAL_MIN_MIN}
          max={KEEP_AWAKE_INTERVAL_MIN_MAX}
          ariaLabel="Keep-awake interval (minutes)"
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={outOfRange || mutation.isPending}
          className={primaryButtonClass}
        >
          Save
        </button>
      </div>
      {outOfRange && (
        <p role="alert" className={errorText}>
          must be between {KEEP_AWAKE_INTERVAL_MIN_MIN} and {KEEP_AWAKE_INTERVAL_MIN_MAX}
        </p>
      )}
      <SettingErrorText mutation={mutation} />
    </div>
  );
}

function PrinterSection({ rows }: { rows: SettingRow[] }) {
  return (
    <section className={panel}>
      <h2 className={panelHeading}>Printer</h2>
      <p className={helpText}>
        Changing init strategy, bit order, or flip pins can produce garbage prints on the wrong hardware -- this
        printer&apos;s hardware-verified combination is Classic / MSB first / Flip pins on.
      </p>
      <div className="mt-3">
        <SelectSettingRow label="Printer mode" fieldKey="printer_mode" rows={rows} options={PRINTER_MODE_OPTIONS} />
        <SelectSettingRow
          label="Init strategy"
          fieldKey="printer_init_strategy"
          rows={rows}
          options={INIT_STRATEGY_OPTIONS}
        />
        <SelectSettingRow label="Bit order" fieldKey="printer_bit_order" rows={rows} options={BIT_ORDER_OPTIONS} />
        <SwitchSettingRow label="Flip pins" fieldKey="printer_flip_pins" rows={rows} />
      </div>
      <div className="mt-3 border-t border-deck-800 pt-3">
        <SwitchSettingRow
          label="Keep printer awake"
          fieldKey="keep_printer_awake"
          rows={rows}
          resetLabel="Reset to default"
        />
        <KeepAwakeIntervalField rows={rows} />
        <p className={helpText}>
          Sends a status request every N minutes to stop the printer&apos;s auto power-off idle timer (USB mode
          only).
        </p>
      </div>
    </section>
  );
}

// --- HomeBox section: URL (buffered text + Save/Clear), API key --------
// (write-only: never populated from the server, only "set"/"not set" plus
// Save-to-replace/Clear), and the existing qr_base_url panel from before
// this task, unchanged in behavior.

function homeboxUrlError(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null; // blank means "clear on save", always valid to submit
  const value = trimmed.replace(/\/+$/, "");
  if (!/^https?:\/\//.test(value) || value === "http://" || value === "https://") {
    return "must be an http(s) URL, e.g. https://homebox.example.com";
  }
  if (/\s/.test(value)) return "must not contain whitespace";
  return null;
}

function HomeboxUrlField({ rows }: { rows: SettingRow[] }) {
  const row = findRow(rows, "homebox_url");
  const serverValue = typeof row?.value === "string" ? row.value : null;
  const mutation = useUpdateSettings();
  const [raw, setRaw] = useState(serverValue ?? "");

  // Resyncs FROM the server value only when it actually changes (a fresh
  // load, a successful save, or a "Reset to env"/Clear) -- never clobbers
  // an in-progress, not-yet-saved edit, same reasoning as ui/inputs.tsx's
  // NumberInput.
  useEffect(() => {
    setRaw(serverValue ?? "");
  }, [serverValue]);

  const validityError = homeboxUrlError(raw);

  function handleSave() {
    const trimmed = raw.trim();
    mutation.mutate({ homebox_url: trimmed === "" ? null : trimmed.replace(/\/+$/, "") });
  }

  function handleClear() {
    mutation.mutate({ homebox_url: null });
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label htmlFor="homebox-url" className={fieldLabelText}>
          HomeBox URL
        </label>
        {row && <ProvenanceBadge source={row.source} />}
      </div>
      <TextInput id="homebox-url" value={raw} onChange={setRaw} placeholder="https://homebox.example.com" maxLength={255} />
      {validityError && (
        <p role="alert" className={errorText}>
          {validityError}
        </p>
      )}
      <SettingErrorText mutation={mutation} />
      <div className="mt-2 flex gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={!!validityError || mutation.isPending}
          className={primaryButtonClass}
        >
          Save
        </button>
        <button type="button" onClick={handleClear} disabled={mutation.isPending} className={SECONDARY_BUTTON_CLASS}>
          Clear (use env)
        </button>
      </div>
    </div>
  );
}

function HomeboxApiKeyField({ rows }: { rows: SettingRow[] }) {
  const row = findRow(rows, "homebox_api_key");
  const isSet = row?.set === true;
  const mutation = useUpdateSettings();
  const [raw, setRaw] = useState("");

  function handleSave() {
    const trimmed = raw.trim();
    if (trimmed === "") return; // nothing typed -- Clear is the way to unset, not an empty Save
    mutation.mutate({ homebox_api_key: trimmed }, { onSuccess: () => setRaw("") });
  }

  function handleClear() {
    setRaw("");
    mutation.mutate({ homebox_api_key: null });
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label htmlFor="homebox-api-key" className={fieldLabelText}>
          HomeBox API key
        </label>
        {row && <ProvenanceBadge source={row.source} />}
      </div>
      <p className={helpText}>
        <strong className="text-deck-200">{isSet ? "Key set." : "Not set."}</strong> Never shown once saved -- type a
        new key to replace it.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <TextInput
          id="homebox-api-key"
          value={raw}
          onChange={setRaw}
          placeholder={isSet ? "enter a new key to replace it" : "hb_..."}
          type="password"
          autoComplete="off"
          maxLength={500}
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={raw.trim() === "" || mutation.isPending}
          className={primaryButtonClass}
        >
          Save
        </button>
        {isSet && (
          <button type="button" onClick={handleClear} disabled={mutation.isPending} className={SECONDARY_BUTTON_CLASS}>
            Clear
          </button>
        )}
      </div>
      <SettingErrorText mutation={mutation} />
    </div>
  );
}

function QrBaseUrlPanel() {
  const queryClient = useQueryClient();
  const settingsQuery = useHomeboxSettingsQuery();

  const [qrBaseUrl, setQrBaseUrl] = useState("");
  const [initialized, setInitialized] = useState(false);

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
    <section className="border-t border-deck-800 pt-4">
      <h3 className={panelHeading}>QR base URL</h3>
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
            .../a/&lt;assetId&gt;). Leave blank to fall back to the HomeBox URL set above.
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
            <button type="button" onClick={handleClear} disabled={saveMutation.isPending} className={SECONDARY_BUTTON_CLASS}>
              Clear (use fallback)
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function HomeboxSection({ rows }: { rows: SettingRow[] }) {
  return (
    <section className={panel}>
      <h2 className={panelHeading}>HomeBox</h2>
      <div className="flex flex-col gap-4">
        <HomeboxUrlField rows={rows} />
        <HomeboxApiKeyField rows={rows} />
        <SwitchSettingRow
          label="Allow writes to HomeBox"
          fieldKey="homebox_writes_enabled"
          rows={rows}
          resetLabel="Reset to default"
          help="Lets this app create items and upload photos in HomeBox. Your HomeBox API key needs write access."
        />
        <QrBaseUrlPanel />
      </div>
    </section>
  );
}

// --- ELS section: els_enabled (Switch, task 4.5 Track A -- moved here from
// the read-only Runtime section now that it's DB-editable) + els_tape_mm
// (buffered number + Save + Reset to env) ---

function ElsTapeMmField({ rows }: { rows: SettingRow[] }) {
  const row = findRow(rows, "els_tape_mm");
  const serverValue = typeof row?.value === "number" ? row.value : null;
  const mutation = useUpdateSettings();
  const [value, setValue] = useState<number | undefined>(serverValue ?? undefined);

  useEffect(() => {
    setValue(serverValue ?? undefined);
  }, [serverValue]);

  const outOfRange = value === undefined || value < ELS_TAPE_MM_MIN || value > ELS_TAPE_MM_MAX;

  function handleSave() {
    if (outOfRange || value === undefined) return;
    mutation.mutate({ els_tape_mm: value });
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center text-deck-200">
          ELS tape width (mm)
          {row && <ProvenanceBadge source={row.source} />}
        </span>
        {row?.source === "db" && (
          <ResetToEnvButton onClick={() => mutation.mutate({ els_tape_mm: null })} disabled={mutation.isPending} />
        )}
      </div>
      <div className="flex items-center gap-2">
        <NumberInput
          value={value}
          onChange={setValue}
          min={ELS_TAPE_MM_MIN}
          max={ELS_TAPE_MM_MAX}
          ariaLabel="ELS tape width (mm)"
        />
        <button type="button" onClick={handleSave} disabled={outOfRange || mutation.isPending} className={primaryButtonClass}>
          Save
        </button>
      </div>
      {outOfRange && (
        <p role="alert" className={errorText}>
          must be between {ELS_TAPE_MM_MIN} and {ELS_TAPE_MM_MAX}
        </p>
      )}
      <SettingErrorText mutation={mutation} />
    </div>
  );
}

function ElsSection({ rows }: { rows: SettingRow[] }) {
  const elsEnabled = findRow(rows, "els_enabled")?.value === true;
  return (
    <section className={panel}>
      <h2 className={panelHeading}>ELS</h2>
      <p className={helpText}>
        HomeBox&apos;s External Label Service: turning this on registers an{" "}
        <strong className="text-deck-200">unauthenticated</strong> endpoint that renders label PNGs on request --
        HomeBox&apos;s label-service caller sends no credentials at all, so this only belongs on a trusted network.
      </p>
      <div className="mt-3">
        <SwitchSettingRow label="ELS enabled" fieldKey="els_enabled" rows={rows} />
      </div>
      <p className={helpText}>
        The tape width HomeBox&apos;s External Label Service renders labels at. Only takes effect while ELS is
        enabled -- currently <span className="font-mono text-deck-200">{elsEnabled ? "enabled" : "disabled"}</span>.
      </p>
      <div className="mt-3">
        <ElsTapeMmField rows={rows} />
      </div>
    </section>
  );
}

// --- Runtime section: read-only, env-derived rows -------------------------

function ReadOnlyRow({ label, row }: { label: string; row: SettingRow | undefined }) {
  if (!row) return null;
  const display = Array.isArray(row.value)
    ? row.value.join(", ")
    : typeof row.value === "boolean"
      ? row.value
        ? "yes"
        : "no"
      : String(row.value);
  return (
    <div className="flex items-center justify-between gap-3 border-b border-deck-800 py-1.5 text-[13px] last:border-b-0">
      <span className="flex items-center text-deck-400">
        {label}
        <ProvenanceBadge source={row.source} />
      </span>
      <span className="font-mono text-deck-200">{display}</span>
    </div>
  );
}

function RuntimeSection({ rows }: { rows: SettingRow[] }) {
  return (
    <section className={panel}>
      <h2 className={panelHeading}>Runtime</h2>
      <p className={helpText}>Every row below is set via the environment -- change it there and restart the app, not here.</p>
      <div className="mt-3">
        <ReadOnlyRow label="Auth mode" row={findRow(rows, "auth_mode")} />
        <ReadOnlyRow label="CORS origins" row={findRow(rows, "cors_origins")} />
        <ReadOnlyRow label="Data directory" row={findRow(rows, "data_dir")} />
      </div>
    </section>
  );
}

/** The Settings page (task 4.5 rework): Appearance (device-local theme,
 * unchanged from before this task) plus a DB-backed overlay over this
 * app's runtime config -- Printer/HomeBox/ELS are genuinely editable, no
 * restart required, each row showing WHERE its current value comes from
 * (db/env/default) and a way back to the env value when overridden;
 * Runtime is what's left that's still env-only. */
export function Settings() {
  const settingsQuery = useSettingsQuery();
  const rows = settingsQuery.data?.settings ?? [];

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <h1 className={typeHeading}>Settings</h1>

      <section className={panel}>
        <h2 className={panelHeading}>Appearance</h2>
        <div className="flex flex-col gap-2">
          <ThemeToggle />
          <p className={helpText}>
            "System" follows this device's own light/dark setting. Stored on this device only -- it isn't a server setting,
            so it doesn't apply to other browsers or devices.
          </p>
        </div>
      </section>

      {settingsQuery.isPending ? (
        <section className={panel}>
          <Pending />
        </section>
      ) : settingsQuery.isError || !settingsQuery.data ? (
        <section className={panel}>
          <p role="alert" className={errorText}>
            Could not load settings.
          </p>
        </section>
      ) : (
        <>
          <PrinterSection rows={rows} />
          <HomeboxSection rows={rows} />
          <ElsSection rows={rows} />
          <RuntimeSection rows={rows} />
        </>
      )}
    </div>
  );
}
