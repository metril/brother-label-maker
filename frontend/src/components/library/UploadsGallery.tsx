import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, deleteImage, getImages, imagePngUrl, postImage } from "../../api/client";
import { useDialogController } from "../../hooks/useDialogController";
import { formatAbsoluteTime, formatRelativeTime } from "../../lib/time";
import { ConfirmDialog } from "../ConfirmDialog";
import { Pending } from "../ui/Pending";
import { errorText, eyebrow, panel } from "../ui/styles";
import type { ImageListItem } from "../../api/types";

const PAGE_SIZE = 24;

/** Bytes -> "245 B" / "2.0 KB" / "1.4 MB" -- no existing helper for this in
 * lib/ (Tape/estimate values are always mm, never bytes), so a small local
 * one; not worth promoting to a shared module for this component's single
 * caller. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The uploads library grid (task D2a): every image previously uploaded
 * through `POST /api/images` (logos/photos for a text label's
 * `icon.kind="image"` art -- see overrides/IconField.tsx's own ImagePicker,
 * the other surface that already posts here), independent of whether any
 * label currently references it. `GET /api/images` scans
 * `data_dir/uploads/*.png` directly (no DB table, see router_images.py's
 * own module docstring), so this component's list is exactly "what's on
 * disk", newest first.
 *
 * Self-contained: owns its own list query, upload mutation, and delete
 * confirm flow, the same "mounting it is the entire integration cost"
 * convention PresetCard.tsx/SequenceCsvUpload.tsx use -- whichever page
 * hosts this (pages/Library.tsx, built separately) needs nothing more than
 * `<UploadsGallery />`.
 *
 * Pagination: `GET /api/images` is server-paginated (page/page_size, same
 * shape as `GET /api/history`) but this component ACCUMULATES pages
 * client-side behind a "Load more" button rather than a Prev/Next pager --
 * a thumbnail grid (like IconField's own symbol picker) reads better as one
 * continuously growing sheet than as a table with page controls. Uploading
 * or deleting an image resets back to page 1 and invalidates the whole
 * `["images"]` query family -- the simplest way to keep the accumulated
 * list correct once a new item enters the newest-first sort or a
 * currently-shown image_id vanishes, at the cost of losing "Load more"
 * progress on that one action (an acceptable trade -- the common case is
 * still page 1 when either happens).
 */
export function UploadsGallery() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ImageListItem[]>([]);
  // Tracks the highest page number already folded into `items` -- guards
  // against re-appending the SAME page's items twice (e.g. a background
  // refetch of an already-accumulated page resolving again with a fresh
  // object reference).
  const appendedPageRef = useRef(0);

  const { data, isPending, isError, isFetching } = useQuery({
    queryKey: ["images", page],
    queryFn: () => getImages(page, PAGE_SIZE),
    placeholderData: (previousData) => previousData,
  });

  useEffect(() => {
    if (!data) return;
    if (data.page === 1) {
      // Page 1 is always a full replace, not an append -- covers both the
      // very first load AND the reset-after-upload/delete case below,
      // regardless of what appendedPageRef currently holds.
      setItems(data.items);
      appendedPageRef.current = 1;
      return;
    }
    if (data.page > appendedPageRef.current) {
      setItems((prev) => [...prev, ...data.items]);
      appendedPageRef.current = data.page;
    }
  }, [data]);

  function resetAndInvalidate() {
    setPage(1);
    queryClient.invalidateQueries({ queryKey: ["images"] });
  }

  const upload = useMutation({
    mutationFn: postImage,
    onSuccess: resetAndInvalidate,
  });

  const [deleteTarget, setDeleteTarget] = useState<ImageListItem | null>(null);
  const deleteDialog = useDialogController();
  const deleteMutation = useMutation({
    mutationFn: (imageId: string) => deleteImage(imageId),
    onSuccess: () => {
      resetAndInvalidate();
      deleteDialog.close();
      setDeleteTarget(null);
    },
  });

  const total = data?.total ?? 0;
  const hasMore = items.length < total;

  return (
    <div className={panel}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <h2 className={eyebrow}>Uploads</h2>
        <div className="flex flex-col items-end gap-1.5">
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label="Upload image"
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
              {upload.error instanceof ApiError ? upload.error.message : "image upload failed"}
            </p>
          )}
        </div>
      </div>

      {isPending ? (
        <Pending />
      ) : isError ? (
        <p role="alert" className={errorText}>
          Could not load uploads.
        </p>
      ) : total === 0 ? (
        <p className="text-[13px] text-deck-400">
          No uploads yet. Upload a logo or photo above to reuse it as icon art on any text label.
        </p>
      ) : (
        <>
          <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {items.map((item) => (
              <li key={item.image_id} className="flex flex-col gap-1.5 rounded-lg border border-deck-800 bg-deck-900/40 p-2">
                <div className="flex aspect-square items-center justify-center overflow-hidden rounded-md border border-deck-600 bg-icon-well p-1.5">
                  <img
                    src={imagePngUrl(item.image_id)}
                    alt={`Upload ${item.image_id}`}
                    loading="lazy"
                    className="h-full w-full object-contain"
                  />
                </div>
                <p className="font-mono text-[11px] text-deck-200" title={formatAbsoluteTime(item.mtime)}>
                  {item.width}×{item.height} · {formatBytes(item.size_bytes)}
                </p>
                <p className="font-mono text-[10px] text-deck-400">{formatRelativeTime(item.mtime)}</p>
                <button
                  type="button"
                  onClick={() => {
                    setDeleteTarget(item);
                    deleteDialog.open();
                  }}
                  aria-label={`Delete upload ${item.image_id}`}
                  className="self-start text-[11px] font-medium text-rust-500 hover:underline"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="font-mono text-[12px] text-deck-400">
              {items.length} of {total} upload{total === 1 ? "" : "s"}
            </p>
            {hasMore && (
              <button
                type="button"
                onClick={() => setPage((p) => p + 1)}
                disabled={isFetching}
                className="rounded-md border border-deck-600 bg-deck-800 px-4 py-1.5 text-[13px] font-medium text-deck-200 hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isFetching ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        </>
      )}

      <ConfirmDialog
        open={deleteDialog.isOpen}
        onClose={() => {
          deleteDialog.close();
          setDeleteTarget(null);
        }}
        closeButtonRef={deleteDialog.closeButtonRef}
        label={deleteTarget ? `Delete upload ${deleteTarget.image_id}?` : "Delete upload?"}
        message="Delete this uploaded image? Any label that still references it will fail to render. This can't be undone."
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        error={deleteMutation.isError ? (deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "delete failed") : null}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.image_id)}
      />
    </div>
  );
}
