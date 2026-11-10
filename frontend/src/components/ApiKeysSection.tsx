import { useState } from "react";
import { ApiError } from "../api/client";
import type { ApiKey, ApiKeyCreated } from "../api/types";
import { useApiKeysQuery, useCreateApiKey, useRevokeApiKey } from "../hooks/useApiKeys";
import { useDialogController } from "../hooks/useDialogController";
import { formatAbsoluteTime, formatRelativeTime } from "../lib/time";
import { ConfirmDialog } from "./ConfirmDialog";
import { Pending } from "./ui/Pending";
import { Select, TextInput } from "./ui/inputs";
import { errorText, fieldLabelText, helpText, panel, panelHeading, primaryButtonClass } from "./ui/styles";

const SCOPE_OPTIONS = [
  { value: "read", label: "Read (GET only)" },
  { value: "write", label: "Write (full access)" },
];

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/** Settings > API keys: machine-client bearer keys for `AUTH_MODE=oidc`
 * deployments. The plaintext is shown exactly once, right after creation. */
export function ApiKeysSection() {
  const query = useApiKeysQuery();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const revokeDialog = useDialogController();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write">("read");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [target, setTarget] = useState<ApiKey | null>(null);

  function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate(
      { name: trimmed, scope },
      {
        onSuccess: (key) => {
          setCreated(key);
          setCopied(false);
          setName("");
        },
      },
    );
  }

  async function handleCopy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  function closeRevoke() {
    revokeDialog.close();
    setTarget(null);
  }

  const keys = query.data ?? [];

  return (
    <section className={panel}>
      <h2 className={panelHeading}>API keys</h2>
      <p className={helpText}>
        Bearer keys for scripts and other machines (<span className="font-mono">Authorization: Bearer lm_…</span>).
        They only matter when the app runs with OIDC sign-in; with no auth they are ignored. Keys cannot manage keys.
      </p>

      {created && (
        <div role="status" className="mt-3 rounded-md border border-amber-500 bg-deck-800 p-3 text-[13px]">
          <p className="text-deck-200">
            Key <strong>{created.name}</strong> created. Copy it now -- it will not be shown again.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="break-all font-mono text-deck-200">{created.key}</code>
            <button type="button" onClick={() => void handleCopy()} className={primaryButtonClass}>
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              onClick={() => setCreated(null)}
              className="text-[11px] font-medium text-deck-400 underline decoration-dotted hover:text-amber-300"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="api-key-name" className={fieldLabelText}>
            Key name
          </label>
          <TextInput id="api-key-name" value={name} onChange={setName} maxLength={100} placeholder="e.g. home automation" />
        </div>
        <div>
          <span className={fieldLabelText}>Scope</span>
          <Select
            value={scope}
            onChange={(v) => setScope(v === "write" ? "write" : "read")}
            options={SCOPE_OPTIONS}
            ariaLabel="Key scope"
          />
        </div>
        <button
          type="button"
          onClick={handleCreate}
          disabled={!name.trim() || create.isPending}
          className={primaryButtonClass}
        >
          Create key
        </button>
      </div>
      {create.isError && (
        <p role="alert" className={errorText}>
          {message(create.error, "Could not create the key.")}
        </p>
      )}

      <div className="mt-4">
        {query.isPending ? (
          <Pending />
        ) : query.isError ? (
          <p role="alert" className={errorText}>
            Could not load API keys.
          </p>
        ) : keys.length === 0 ? (
          <p className={helpText}>No API keys yet.</p>
        ) : (
          <ul>
            {keys.map((k) => (
              <li
                key={k.id}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-deck-800 py-2 text-[13px] last:border-b-0"
              >
                <span className="text-deck-200">
                  {k.name}
                  <span className="ml-2 font-mono text-deck-400">lm_{k.prefix}…</span>
                  <span className="ml-2 rounded border border-deck-700 px-1 py-0.5 font-condensed text-[9px] uppercase tracking-wide text-deck-400">
                    {k.scope}
                  </span>
                </span>
                <span className="flex items-center gap-3 text-[12px] text-deck-400">
                  <span title={formatAbsoluteTime(k.created_at)}>created {formatRelativeTime(k.created_at)}</span>
                  <span>{k.last_used_at ? `used ${formatRelativeTime(k.last_used_at)}` : "never used"}</span>
                  <button
                    type="button"
                    aria-label={`Revoke ${k.name}`}
                    onClick={() => {
                      setTarget(k);
                      revokeDialog.open();
                    }}
                    className="font-medium text-rust-500 underline decoration-dotted hover:text-amber-300"
                  >
                    Revoke
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={revokeDialog.isOpen}
        onClose={closeRevoke}
        closeButtonRef={revokeDialog.closeButtonRef}
        label={target ? `Revoke ${target.name}?` : "Revoke key?"}
        message="Revoke this key? Anything using it stops working immediately. This can't be undone."
        confirmLabel="Revoke"
        isPending={revoke.isPending}
        error={revoke.isError ? message(revoke.error, "revoke failed") : null}
        onConfirm={() => target && revoke.mutate(target.id, { onSuccess: closeRevoke })}
      />
    </section>
  );
}
