import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, deleteImage, getImages, imageThumbUrl, postImage } from "../../api/client";
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
 * hosts this (pages/Library.tsx) needs nothing more than `<UploadsGallery
 * />`. `h-full min-h-0 flex-col` on the panel (2026-08 layout rework) lets
 * it fill whatever height its host gives it -- Library.tsx's "Uploads" tab
 * passes the full remaining viewport height -- with the thumbnail grid as
 * the one scrolling region (`min-h-0 flex-1 overflow-y-auto`) between the
 * fixed upload-control header and the fixed count/"Load more" footer,
 * instead of the grid growing the whole page. A host that doesn't bound
 * this component's height (there isn't one today) just gets its natural
 * content height, same as before -- `h-full` against an unbounded parent
 * resolves to `auto`.
 *
 * Pagination: `GET /api/images` is server-paginated (page/page_size, same
 * shape as `GET /api/history`) but this component ACCUMULATES pages
 * client-side behind a "Load more" button rather than a Prev/Next pager --
 * a thumbnail grid (like IconField's own symbol picker) reads better as one
 * continuously growing sheet than as a table with page controls. Built on
 * react-query's own `useInfiniteQuery` (M11, docs/code-review-2026-08.md)
 * -- every loaded page lives under the ONE `["images"]` query key, not one
 * `["images", page]` entry per page number, so `invalidateQueries({
 * queryKey: ["images"]})` after an upload/delete refetches EVERY page
 * currently loaded, not just the first. The PREVIOUS hand-rolled version
 * tracked a `page` state var plus an `appendedPageRef` high-water mark and
 * manually accumulated `data.items` into local state on every fetch; that
 * scheme had a real gap -- `invalidateQueries` only refetches ACTIVE
 * queries by default, so a background refetch of an already-loaded (now
 * inactive) `["images", 2]` entry could resolve with fresh data AFTER the
 * ref guard had already moved past it, and the stale slice then displayed
 * permanently (see M11's own repro: load more, then delete/upload, then
 * load more again). `useInfiniteQuery` has no such gap: there is only ever
 * ONE query, its `data.pages` array is what "loaded so far" means, and a
 * refetch replaces the whole array atomically.
 */
export function UploadsGallery() {
  const queryClient = useQueryClient();

  const {
    data,
    isPending,
    isError,
    isFetching,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
  } = useInfiniteQuery({
    queryKey: ["images"],
    queryFn: ({ pageParam }) => getImages(pageParam, PAGE_SIZE),
    initialPageParam: 1,
    // A next page exists iff fewer items are loaded so far (summed across
    // every page already in `allPages`) than the server's own `total` --
    // the same figure on every page of the same listing.
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loaded < lastPage.total ? lastPage.page + 1 : undefined;
    },
  });

  const items: ImageListItem[] = data?.pages.flatMap((page) => page.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  function resetAndInvalidate() {
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

  const hasMore = hasNextPage ?? false;

  return (
    <div className={`${panel} flex h-full min-h-0 flex-col`}>
      <div className="mb-4 flex shrink-0 flex-wrap items-start justify-between gap-3">
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
          {/* The one scrolling region: denser auto-fill columns (a fixed
              `minmax(8rem, 1fr)` tile floor, not a breakpoint-capped
              `lg:grid-cols-6`) pack more thumbnails per row as the panel
              gets wider, and `min-h-0 flex-1 overflow-y-auto` lets this
              div -- not the whole page -- absorb the grid's height, same
              "own scroll region" treatment as SymbolBrowser's browse-mode
              grid. */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(8rem,1fr))] gap-4 pb-1">
              {items.map((item) => (
                <li key={item.image_id} className="flex flex-col gap-1.5 rounded-lg border border-deck-800 bg-deck-900/40 p-2">
                  <div className="flex aspect-square items-center justify-center overflow-hidden rounded-md border border-deck-600 bg-icon-well p-1.5">
                    <img
                      src={imageThumbUrl(item.image_id)}
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
          </div>

          <div className="mt-4 flex shrink-0 items-center justify-between gap-3">
            <p className="font-mono text-[12px] text-deck-400">
              {items.length} of {total} upload{total === 1 ? "" : "s"}
            </p>
            {hasMore && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetching}
                className="rounded-md border border-deck-600 bg-deck-800 px-4 py-1.5 text-[13px] font-medium text-deck-200 hover:border-deck-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
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
