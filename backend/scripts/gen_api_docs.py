"""Generate `openapi.json` and the endpoint reference in `API.md`.

Usage: `uv run python scripts/gen_api_docs.py [--check]`. With `--check`
nothing is written; exit status 1 means the committed files drifted from the
code (run without the flag to fix).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from labelmaker.config import AppConfig
from labelmaker.main import create_app

ROOT = Path(__file__).resolve().parents[2]
BEGIN = "<!-- BEGIN GENERATED -->"
END = "<!-- END GENERATED -->"
_METHODS = ("get", "post", "put", "patch", "delete")
_AUTH = {
    "none": "none",
    "read": "read key or session",
    "write": "write key or session",
    "session": "session only",
}


def build_spec() -> dict:
    # Fixed config: the schema must not depend on the caller's environment.
    cfg = AppConfig(auth_mode="none", data_dir=Path("/nonexistent"))
    spec = create_app(cfg, static_dir=None).openapi()
    # The live /openapi.json reports the real package version; the committed
    # file pins a constant so a release bump does not trip the drift gate.
    spec["info"]["version"] = "0"
    return spec


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_reference(spec: dict) -> str:
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, item in spec["paths"].items():
        for method in _METHODS:
            if method in item:
                op = item[method]
                by_tag.setdefault(op["tags"][0], []).append((method.upper(), path, op))
    out: list[str] = []
    for tag in spec["tags"]:
        ops = by_tag.get(tag["name"], [])
        if not ops:
            continue
        out += [f"### {tag['name']}", "", tag["description"], ""]
        out += [
            "| Method | Path | Summary | Auth | Success | Errors |",
            "|---|---|---|---|---|---|",
        ]
        for method, path, op in ops:
            codes = list(op["responses"])
            ok = ", ".join(c for c in codes if c.isdigit() and int(c) < 400)
            errs = ", ".join(c for c in codes if c.isdigit() and int(c) >= 400)
            out.append(
                f"| {method} | `{path}` | {_cell(op['summary'])} | "
                f"{_AUTH[op['x-required-scope']]} | {ok} | {errs} |"
            )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def splice(doc: str, generated: str) -> str:
    head, sep, rest = doc.partition(BEGIN)
    _, sep2, tail = rest.partition(END)
    if not sep or not sep2:
        sys.exit(f"API.md is missing the {BEGIN} / {END} markers")
    return f"{head}{BEGIN}\n\n{generated}\n{END}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail on drift instead of writing")
    args = parser.parse_args()

    spec = build_spec()
    openapi_text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    api_md = ROOT / "API.md"
    md_text = splice(api_md.read_text(encoding="utf-8"), render_reference(spec))
    targets = {ROOT / "openapi.json": openapi_text, api_md: md_text}

    drift = [p for p, text in targets.items() if not p.exists() or p.read_text("utf-8") != text]
    if args.check:
        for p in drift:
            print(f"drift: {p.relative_to(ROOT)} is stale; run `make api-docs`", file=sys.stderr)
        return 1 if drift else 0
    for p in drift:
        p.write_text(targets[p], encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
