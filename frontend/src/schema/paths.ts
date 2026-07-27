export type PathSegment = string | number;

/** Immutable nested update by path -- `setAtPath(params, ["blocks", 2,
 * "lines", 0], "PORT 3")` returns a new params object/array at every level
 * the path touches, structurally sharing everything else. Used by every
 * SchemaField control instead of each one hand-rolling its own nested
 * spread, so a 3-level-deep breaker_box.breakers[i].lines[j] edit is no
 * different from a top-level one. */
export function setAtPath<T>(obj: T, path: PathSegment[], value: unknown): T {
  if (path.length === 0) return value as T;
  const [head, ...rest] = path as [PathSegment, ...PathSegment[]];

  if (typeof head === "number") {
    const arr = Array.isArray(obj) ? [...obj] : [];
    arr[head] = rest.length === 0 ? value : setAtPath(arr[head], rest, value);
    return arr as T;
  }

  const record: Record<string, unknown> =
    obj && typeof obj === "object" && !Array.isArray(obj) ? { ...(obj as Record<string, unknown>) } : {};
  record[head] = rest.length === 0 ? value : setAtPath(record[head], rest, value);
  return record as T;
}
