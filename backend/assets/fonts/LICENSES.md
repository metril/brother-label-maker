# Bundled fonts

Static (non-variable) TTFs only, chosen for deterministic rendering: resvg
renders a fixed weight/style directly from a static font file's outline data,
with no variable-axis interpolation step whose result could vary across
resvg/fontdb versions.

| Family | File(s) | Version | Source | License |
| --- | --- | --- | --- | --- |
| Inter | `Inter-Regular.ttf`, `Inter-Bold.ttf` | 4.1 | [rsms/inter release v4.1](https://github.com/rsms/inter/releases/tag/v4.1), asset `Inter-4.1.zip`, files `extras/ttf/Inter-Regular.ttf` / `extras/ttf/Inter-Bold.ttf` | SIL Open Font License 1.1 |
| Roboto Condensed | `RobotoCondensed-Regular.ttf`, `RobotoCondensed-Bold.ttf` | 3.008 | [googlefonts/roboto-classic release v3.008](https://github.com/googlefonts/roboto-classic/releases/tag/v3.008), asset `Roboto_v3.008.zip`, files `Roboto_v3.008/web/static/RobotoCondensed-{Regular,Bold}.ttf` | Apache License 2.0 (per the release's bundled `LICENSE.txt`; Google Fonts' current metadata for this family lists "OFL" for its `ofl/` catalog directory, but the upstream release artifact itself is Apache-2.0-licensed) |
| JetBrains Mono | `JetBrainsMono-Regular.ttf`, `JetBrainsMono-Bold.ttf` | 2.304 | [JetBrains/JetBrainsMono tag v2.304](https://github.com/JetBrains/JetBrainsMono/tree/v2.304), files `fonts/ttf/JetBrainsMono-{Regular,Bold}.ttf` | SIL Open Font License 1.1 |
| DejaVu Sans | `DejaVuSans.ttf` (style "Book"), `DejaVuSans-Bold.ttf` | 2.37 | [dejavu-fonts/dejavu-fonts release version_2_37](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37), asset `dejavu-fonts-ttf-2.37.zip`, files `dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf` / `DejaVuSans-Bold.ttf` | DejaVu Fonts License (Bitstream Vera-derived permissive free license; DejaVu-specific changes are public domain) |

All four downloads succeeded from their official upstream GitHub release
sources (not vendored copies) — the system DejaVu fallback described in the
task brief was not needed. The installed `fonts-dejavu-core` package on this
machine happens to already be the same 2.37 upstream version, but it is
**not** byte-identical to the copy bundled here (`cmp` confirms they differ,
first byte at offset 17) — Debian repackages/rehints the upstream TTFs
rather than shipping them verbatim, so "same version" does not mean "same
bytes."

Declared family/style names (verified via `PIL.ImageFont.truetype(...).getname()`
against the actual files in this directory, not assumed from filenames):

| File | Family | Style |
| --- | --- | --- |
| `Inter-Regular.ttf` | Inter | Regular |
| `Inter-Bold.ttf` | Inter | Bold |
| `RobotoCondensed-Regular.ttf` | Roboto Condensed | Regular |
| `RobotoCondensed-Bold.ttf` | Roboto Condensed | Bold |
| `JetBrainsMono-Regular.ttf` | JetBrains Mono | Regular |
| `JetBrainsMono-Bold.ttf` | JetBrains Mono | Bold |
| `DejaVuSans.ttf` | DejaVu Sans | Book |
| `DejaVuSans-Bold.ttf` | DejaVu Sans | Bold |
