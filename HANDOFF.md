# PT-E720BT Linux driver — handoff

**Objective:** native Linux printing to the Brother PT-E720BT (P-touch EDGE
720BT) without Brother's app or Windows driver. USB raster path is confirmed
working; goal is a `ptouch-print` device entry that prints a real label,
then (stretch) Bluetooth.

**Status:** USB status channel confirmed. Standard Brother raster protocol.
Not yet: a successful print, media-type decode, any Bluetooth work.

---

## Confirmed hardware facts (from status probe, USB)

- **USB VID:PID** = `0x04f9:0x224a`  ← device-table key
- **Model code** = `0x81` (status byte 4) — the E720BT signature; differs
  from the P750W family, match on this
- **Endpoints**: bulk OUT `0x02`, bulk IN `0x81`
- **Head width**: 128 px (24 mm @ 180 dpi) → raster line = 16 bytes
- **Status request** `1B 69 53` returns a valid 32-byte block (`80 20 42` header)

### Decoded status block
Raw: `80 20 42 30 81 30 00 00 00 00 18 14 01 00 00 00 00 00 00 00 00 00 00 00 90 08 00 00 00 00 00 00`

| byte | val  | meaning                                   |
|------|------|-------------------------------------------|
| 0    | 0x80 | print-head mark (fixed)                   |
| 1    | 0x20 | block size = 32 (fixed)                   |
| 2    | 0x42 | 'B' (fixed)                               |
| 3    | 0x30 | series code                               |
| 4    | 0x81 | **model code — E720BT**                   |
| 5    | 0x30 | country code                              |
| 8    | 0x00 | error info 1 — none                       |
| 9    | 0x00 | error info 2 — none                       |
| 10   | 0x18 | media width = 24 mm                       |
| 11   | 0x14 | **media type — UNDECODED, resolve first** |
| 12   | 0x01 | number of colors = 1                      |
| 18   | 0x00 | status type = reply to request            |
| 24   | 0x90 | tape color (per ptouch `--info` decode)   |
| 25   | 0x08 | text color = black (per ptouch decode)    |

`0x14` at byte 11 is outside the P750W-family media table. This is expected —
2025 model, extended enum. **Do not guess it.** Decode empirically (task 3).

---

## Already built (in this repo / prior work)

- `brother_probe.py` — pyusb status probe. Sends flush→`ESC @`→`ESC i S`,
  parses the 32-byte reply. This is what produced the facts above.
- Docker wrapper (`Dockerfile`, `docker-compose.yml`) — runs the probe with
  `--privileged -v /dev/bus/usb:/dev/bus/usb`. Optional; native pyusb is
  simpler for iteration.

---

## Protocol quick-reference (print path)

Confident from the PT-E550W/P750W/P710BT raster manual (same family):

```
100 × 00               flush / invalidate
1B 40                  ESC @   initialize
1B 69 61 01            ESC i a 01   switch to raster mode
1B 69 7A <10 bytes>    ESC i z   print information  (see below)
1B 69 4D <n>           ESC i M   mode   (bit 0x40 = auto-cut, 0x80 = mirror)
1B 69 64 <n1> <n2>     ESC i d   feed/margin amount (dots, LE 16-bit)
4D 02                  M 02   select PackBits (TIFF) compression
47 <len> <data...>     G   one compressed raster line   (5A = 'Z' = blank line)
...                    repeat G per line
1A                     Ctrl-Z   print WITH feed (final page)
0C                     FF   print WITHOUT feed (non-final page)
```

**Print-information command, decoded from the manual's 24 mm example**
`1B 69 7A 84 00 18 00 9C 02 00 00 00 00`:
- `84` = valid flags (PI_RECOVER 0x80 | PI_WIDTH 0x04)
- `00` = media type
- `18` = width mm (24)
- `00` = length mm
- `9C 02 00 00` = raster line count, LE (0x029C = 668 in the example)
- `00 00` = starting page / trailing

**Verify against the manual, don't take my word:** the exact bit
definitions of `ESC i M` beyond auto-cut, and `ESC i K` (advanced mode).
Half-cut is irrelevant here — this hardware has a single full auto-cutter,
not the dual/half cutter of the 1.5 in sibling.

---

## Tasks (ordered)

1. **Clone + build upstream.**
   `git clone https://github.com/hannesweisbach/ptouch-print`
   Build (autotools + libusb-1.0-dev). Confirm it compiles and `--info`
   runs (it'll say the E720BT is unsupported — expected).

2. **Add the device entry.** In `src/libptouch.c`, the `ptdevs[]` table
   (`struct pt_dev_info`). Add:
   `{0x04f9, 0x224a, "PT-E720BT", 128, <flags>}`.
   Read the current flag enum in the header — don't assume names. Start by
   copying the flags from the **PT-P710BT / PT-P750W** entry (same 128 px
   family); most likely `FLAG_RASTER_PACKBITS | FLAG_P700_INIT`. The P700
   lineage needs the raster-mode init line above; if prints come out blank
   or "unknown format," that flag is the first thing to toggle.

3. **Decode media type `0x14`.** Swap between the two kit tapes and re-probe
   byte 11 to build the table by elimination:
   - `brother_probe.py --raw` (or `ptouch-print --info`) with TZe-S221
     laminated loaded → record byte 11
   - repeat with TZe-FX251 flexible → record byte 11
   Whatever is loaded now (reporting `0x14`) is one of those two. Add both
   to the media table.

4. **Print one label.** `./ptouch-print --text "E720BT"`.
   Success = loop closed. Failure modes and where to look:
   - blank feed → raster-mode init flag (task 2), or missing `ESC i a 01`
   - "unsupported/unknown format" → same init flag
   - cut in wrong place / no cut → `ESC i M` auto-cut bit + margin `ESC i d`
   - image offset within tape → per-tape-width margin/centering (16-byte
     line, image centered in 128 px)

5. **Upstream it (optional).** If it prints cleanly, PR the device entry —
   this model isn't in mainline yet.

6. **Bluetooth (separate, stretch).** BT 5.0 on a 2025 model may be BLE GATT
   rather than Classic SPP. If SPP: same byte stream over an RFCOMM socket,
   trivial. If GATT: find the write characteristic, chunk with
   write-without-response, and the status notify characteristic for the
   32-byte block. Needs its own probe — do not assume SPP.

---

## References

- Family raster manual (E550W / P750W / P710BT) — primary spec:
  https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf
- P900 raster manual (adds network/BT port notes):
  https://download.brother.com/welcome/docp100407/cv_ptp900_eng_raster_102.pdf
- ptouch-print upstream: https://github.com/hannesweisbach/ptouch-print
- CUPS-driver alternative (rastertoptch.c, useful cross-reference):
  https://github.com/philpem/printer-driver-ptouch

## Caveats

- The print `ESC i M` / `ESC i K` bit fields beyond auto-cut are unverified
  here — confirm against the manual before trusting.
- Media byte `0x14` is a real unknown; task 3 is a prerequisite for correct
  media handling, not optional polish.
- Everything above is USB-only. The Pro Label Tool "exclusive app" framing
  did NOT gate the status channel, but the *print* path is unproven until
  task 4 succeeds.