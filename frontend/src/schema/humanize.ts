// Turns a pydantic field name (snake_case, sometimes carrying a unit
// suffix) into a display label -- used instead of the schema's own `title`
// (pydantic's auto-title-cases the raw field name verbatim, e.g.
// "Block Length Mm" -- readable but the unit reads as a stray capitalized
// word). Units get parenthesized and lowercased instead: "Block length (mm)".

const UNIT_SUFFIXES: Record<string, string> = {
  mm: "mm",
  px: "px",
};

const WORD_OVERRIDES: Record<string, string> = {
  id: "ID",
  qr: "QR",
};

export function humanizeFieldName(key: string): string {
  const words = key.split("_").filter(Boolean);
  if (words.length === 0) return key;

  const last = words[words.length - 1]!.toLowerCase();
  const unit = UNIT_SUFFIXES[last];
  const bodyWords = unit ? words.slice(0, -1) : words;

  const body = bodyWords
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (WORD_OVERRIDES[lower]) return WORD_OVERRIDES[lower];
      return i === 0 ? capitalize(lower) : lower;
    })
    .join(" ");

  if (!body) return unit ? `(${unit})` : key;
  return unit ? `${body} (${unit})` : body;
}

function capitalize(word: string): string {
  return word.length === 0 ? word : word[0]!.toUpperCase() + word.slice(1);
}

/** A string enum VALUE (e.g. "chain_ff", "code128", "4-pair") into a display
 * label -- same word-splitting idea as humanizeFieldName, but on `_` and
 * `-` both (enum values use either), with a few domain overrides for
 * initialisms that shouldn't title-case letter by letter. */
const ENUM_OVERRIDES: Record<string, string> = {
  qr: "QR",
  code128: "Code 128",
  code39: "Code 39",
  datamatrix: "Data Matrix",
  tze: "TZe",
  hse_2_1: "HSe 2:1",
  hse_3_1: "HSe 3:1",
  cut_each: "Cut each",
  chain_ff: "Chain (form-feed)",
  strip_marks: "Chain (strip marks)",
};

export function humanizeEnumValue(value: string): string {
  const override = ENUM_OVERRIDES[value.toLowerCase()];
  if (override) return override;
  return value
    .split(/[_-]/)
    .filter(Boolean)
    .map((word, i) => (i === 0 ? capitalize(word) : word))
    .join(" ");
}
