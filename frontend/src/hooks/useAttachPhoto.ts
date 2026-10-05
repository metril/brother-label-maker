import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { HomeboxAttachmentResponse } from "../api/types";
import { toUploadJpeg } from "../lib/captureImage";

export type AttachErrorKind = "unauthorized" | "forbidden" | "too_large" | "bad_type" | "offline" | "server";

export class AttachError extends Error {
  readonly kind: AttachErrorKind;
  constructor(kind: AttachErrorKind, message: string) {
    super(message);
    this.name = "AttachError";
    this.kind = kind;
  }
}

export type AttachResult = HomeboxAttachmentResponse;

export const ENTITY_QUERY_KEY = (id: string) => ["homebox-entity", id] as const;

function kindForStatus(status: number): AttachErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 413) return "too_large";
  if (status === 415 || status === 422) return "bad_type";
  return "server";
}

function detailFrom(text: string, fallback: string): string {
  try {
    const d: unknown = (JSON.parse(text) as { detail?: unknown }).detail;
    return typeof d === "string" && d ? d : fallback;
  } catch {
    return fallback;
  }
}

/** POST /api/homebox/entities/{id}/attachments as multipart via XHR (fetch
 * has no upload progress). Rejects with a typed AttachError. */
export function uploadAttachment(
  entityId: string,
  file: Blob,
  filename: string,
  primary: boolean,
  onProgress?: (fraction: number) => void,
): Promise<AttachResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/homebox/entities/${encodeURIComponent(entityId)}/attachments`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress?.(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new AttachError("offline", "Can't reach the server."));
    xhr.ontimeout = xhr.onerror;
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as AttachResult);
        } catch {
          reject(new AttachError("server", "Unexpected response from the server."));
        }
        return;
      }
      reject(new AttachError(kindForStatus(xhr.status), detailFrom(xhr.responseText, `Upload failed (${xhr.status}).`)));
    };
    const form = new FormData();
    form.append("file", file, filename);
    form.append("primary", primary ? "true" : "false");
    xhr.send(form);
  });
}

interface AttachVars {
  entityId: string;
  file: File;
  primary: boolean;
}

/** Uploads a photo (re-encoded to JPEG first). On 413 it re-encodes smaller
 * (quality 0.6, 1920px) and retries once. Invalidates the entity query. */
export function useAttachPhoto() {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState(0);

  const mutation = useMutation<AttachResult, AttachError, AttachVars>({
    mutationFn: async ({ entityId, file, primary }) => {
      setProgress(0);
      const jpeg = await toUploadJpeg(file);
      try {
        return await uploadAttachment(entityId, jpeg, jpeg.name, primary, setProgress);
      } catch (err) {
        if (!(err instanceof AttachError) || err.kind !== "too_large") throw err;
        setProgress(0);
        const smaller = await toUploadJpeg(file, 0.6, 1920);
        // Re-encode failed (undecodable image): same bytes would 413 again.
        if (smaller === file) throw err;
        return uploadAttachment(entityId, smaller, smaller.name, primary, setProgress);
      }
    },
    onSuccess: (_data, { entityId }) => {
      void queryClient.invalidateQueries({ queryKey: ENTITY_QUERY_KEY(entityId) });
      void queryClient.invalidateQueries({ queryKey: ["homebox-entities"] });
    },
  });

  const { reset: resetMutation } = mutation;
  const reset = useCallback(() => {
    resetMutation();
    setProgress(0);
  }, [resetMutation]);

  return { attach: mutation.mutate, isPending: mutation.isPending, isSuccess: mutation.isSuccess, error: mutation.error, progress, reset };
}
