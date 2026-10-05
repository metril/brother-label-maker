// Re-encodes a camera photo for upload: decoded via createImageBitmap
// (applies EXIF orientation), drawn to a canvas capped at `maxEdge` on the
// long side, and exported as JPEG -- which also drops all EXIF/GPS metadata
// and turns an iPhone HEIC into a JPEG the backend accepts. Any failure
// (no createImageBitmap, HEIC the browser can't decode, canvas/toBlob
// unavailable) returns the ORIGINAL file so the upload still goes ahead.

export const UPLOAD_MAX_EDGE = 2560;
export const UPLOAD_QUALITY = 0.85;

export async function toUploadJpeg(
  file: File,
  quality: number = UPLOAD_QUALITY,
  maxEdge: number = UPLOAD_MAX_EDGE,
): Promise<File> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    try {
      const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
      const width = Math.max(1, Math.round(bitmap.width * scale));
      const height = Math.max(1, Math.round(bitmap.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return file;
      ctx.drawImage(bitmap, 0, 0, width, height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (!blob || blob.type !== "image/jpeg") return file;
      const base = file.name.replace(/\.[^.]+$/, "") || "photo";
      return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
    } finally {
      bitmap.close();
    }
  } catch {
    return file;
  }
}
