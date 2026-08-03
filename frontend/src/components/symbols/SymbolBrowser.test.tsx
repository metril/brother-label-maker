import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { mockIntersectionObserverInstances } from "../../test/setup";
import { renderWithQueryClient } from "../../test/utils";
import { server } from "../../test/msw/server";
import { trimmedSymbolsFixture } from "../../test/msw/handlers";
import symbolsFixture from "../../test/fixtures/symbols.json";
import { columnCount } from "../../lib/columnCount";
import { SymbolBrowser } from "./SymbolBrowser";

/** Mirrors SymbolBrowser's own category+search predicate (see that
 * component's `filtered` computation) so count-line and presence/absence
 * assertions below stay correct however big/composed the fixture is --
 * the fixture grew from 858 to 8362 entries (5 new icon sources) between
 * commits e62516b and 566655d, and hardcoded counts/identifiers went
 * stale along with it. Runs against `trimmedSymbolsFixture` (H9,
 * docs/code-review-2026-08.md) -- the same slice test/msw/handlers.ts's
 * default `symbolsHandler` actually serves -- not the raw 8362-entry
 * fixture; the one test in this file that needs the full catalog
 * (the scale test at the bottom) overrides the handler and reasons about
 * `symbolsFixture` directly instead. */
function filterFixture(category: string, query: string) {
  const q = query.trim().toLowerCase();
  return trimmedSymbolsFixture.filter((s) => {
    if (category !== "all" && s.category !== category) return false;
    if (!q) return true;
    return s.id.includes(q) || s.name.toLowerCase().includes(q) || s.tags.some((t) => t.includes(q));
  });
}

/** Mirrors the count line's own singular/plural rendering (`{n} symbol{n
 * === 1 ? "" : "s"}`) -- the trimmed slice's per-bucket cap means a
 * category+search combination can genuinely narrow to exactly one match
 * (unlike the raw fixture, where every filtered count used in this file
 * happened to be > 1), so a hardcoded " symbols" would go stale the moment
 * that happens. */
function countText(n: number) {
  return `${n} symbol${n === 1 ? "" : "s"}`;
}

/** Mirrors SymbolBrowser's own (non-exported) CATEGORY_LABELS map, only for
 * the categories this file's picks actually land in. */
const CATEGORY_LABELS: Record<string, string> = {
  general: "General",
  electrical: "Electrical",
  network: "Network",
  av: "AV",
  arrow: "Arrow",
  misc: "Misc",
  safety: "Safety",
};

const ALL_COUNT_TEXT = countText(trimmedSymbolsFixture.length);

/** The trimmed slice packs the head of every (category, source) bucket
 * together, which occasionally puts two icons sharing a plain generic name
 * (e.g. "Add", contributed once by the original bare-id set and again by
 * one of the newer prefixed sources) inside the same window -- fine for
 * the component (ids are always unique) but ambiguous for `getByRole(...,
 * { name })` in a test. Picks the first `count` entries (in the slice's
 * own id order, so still well inside the initial window) whose name is
 * unique across the whole slice, so name-based queries below are
 * unambiguous by construction however the sibling catalog regen reshuffles
 * bucket contents. */
function firstUniquelyNamed(count: number) {
  const nameCounts = new Map<string, number>();
  for (const s of trimmedSymbolsFixture) nameCounts.set(s.name, (nameCounts.get(s.name) ?? 0) + 1);
  return trimmedSymbolsFixture.filter((s) => nameCounts.get(s.name) === 1).slice(0, count);
}

describe("SymbolBrowser: browse mode", () => {
  it("renders the full catalog with a search box and category tabs, no selection chip", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);

    expect(await screen.findByText(ALL_COUNT_TEXT)).toBeInTheDocument();
    expect(screen.getByLabelText("Search symbols")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All" })).toBeInTheDocument();
    // "safety" used to have no entries in the (858-entry) fixture, so its
    // tab didn't show up (the "no empty tabs" rule) -- the regenerated
    // fixture's new sources (lucide_/tabler_/remix_/bootstrap_/fluent_)
    // carry safety-category icons, so it's populated like every other
    // category now.
    expect(screen.getByRole("radio", { name: "Safety" })).toBeInTheDocument();
    expect(screen.queryByText("Clear")).not.toBeInTheDocument();
  });

  it("search filters the grid and the count line updates", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    await user.type(screen.getByLabelText("Search symbols"), "off");
    const offMatches = filterFixture("all", "off");
    expect(screen.getByText(countText(offMatches.length))).toBeInTheDocument();
    // "Camera Video Off" (bootstrap_camera_video_off) -- its name is unique
    // across the trimmed slice and it sorts early enough by id to land
    // inside the initial 96-item window.
    expect(await screen.findByRole("option", { name: "Camera Video Off" })).toBeInTheDocument();
  });

  it("category tabs filter the grid and compose with an active search", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    await user.click(screen.getByRole("radio", { name: "Electrical" }));
    const electrical = filterFixture("electrical", "");
    expect(screen.getByText(countText(electrical.length))).toBeInTheDocument();
    // "Electrical Services" is a uniquely-named electrical icon within the
    // initial window -- "Bolt" (the pre-regeneration example) now names
    // three separate icons (material/lucide/tabler sources), so it's no
    // longer safe to query by that name alone.
    expect(await screen.findByRole("option", { name: "Electrical Services" })).toBeInTheDocument();
    // "AC Unit" is a uniquely-named general-category icon in the trimmed
    // slice -- absent once filtered to Electrical, proving the tab
    // actually filters rather than just relabeling.
    expect(screen.queryByRole("option", { name: "AC Unit" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "All" }));
    await user.type(screen.getByLabelText("Search symbols"), "off");
    await user.click(screen.getByRole("radio", { name: "Network" }));
    const networkOff = filterFixture("network", "off");
    expect(screen.getByText(countText(networkOff.length))).toBeInTheDocument();
    // "Bluetooth Off" (lucide_bluetooth_off) -- the trimmed slice's
    // per-bucket cap only keeps one network+"off" match, so this narrows to
    // exactly 1 (see `countText`'s own comment on why the count-line
    // assertion above can't hardcode "symbols").
    expect(await screen.findByRole("option", { name: "Bluetooth Off" })).toBeInTheDocument();
    // "Camera Video Off" matched the search term but isn't Network-category.
    expect(screen.queryByRole("option", { name: "Camera Video Off" })).not.toBeInTheDocument();
  });

  it("windowing: renders an initial slice of 96 and grows it when the IntersectionObserver sentinel fires", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    expect(screen.getAllByRole("option")).toHaveLength(96);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    observer.trigger();

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(192));
  });

  it("windowing (bug fix): the sentinel is re-armed after each grow, so a STILL-visible sentinel keeps growing the window on repeated intersections", async () => {
    // Before the fix: `observe()` on a target the observer was already
    // observing was a silent no-op, and the sentinel div is the SAME DOM
    // node before and after a grow (only its position in the grid's
    // children moves) -- so the window would grow exactly ONCE no matter
    // how many more times the (still-visible, per this test) sentinel
    // "fired" after that. Triggering the SAME observer instance a SECOND
    // time here proves the unobserve+observe re-arm actually re-establishes
    // observation rather than degrading into a permanent no-op.
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    observer.trigger();
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(192));

    // Pin the MECHANISM, not just the eventual growth: MockIntersectionObserver's
    // `#targets` is a bare Set, so `trigger()` fires for whatever's already
    // in it regardless of whether anything re-observed it -- the growth
    // assertions above (and below) would pass identically even with the
    // entire re-arm effect deleted, since the sentinel never leaves the Set
    // in the first place. Assert directly on the call log instead: the grow
    // above must have produced an unobserve(sentinel) immediately followed
    // by an observe(sentinel) for the SAME node -- the actual re-arm, not a
    // coincidental outcome.
    const sentinel = observer.calls.find((call) => call.op === "observe")!.target;
    const reArmed = observer.calls.some(
      (call, i) =>
        call.op === "unobserve" &&
        call.target === sentinel &&
        observer.calls[i + 1]?.op === "observe" &&
        observer.calls[i + 1]?.target === sentinel,
    );
    expect(reArmed).toBe(true);

    observer.trigger();
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(Math.min(288, trimmedSymbolsFixture.length)));
  });

  it("windowing (bug fix): the sentinel's IntersectionObserver uses the grid's own scroll container as root, not the viewport", async () => {
    // Before the fix: the observer was constructed with no `root` at all,
    // so it measured intersection against the VIEWPORT -- wrong once the
    // grid became its own `overflow-y-auto` scroll region.
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    expect(observer.root).toBe(screen.getByRole("listbox", { name: "Symbol" }));
    expect(observer.rootMargin).toBe("400px");
  });

  it("keyboard nav past the rendered window's edge grows the window and lands focus on the right option", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    // trimmedSymbolsFixture is a content-relative subset of symbols.json,
    // which is sorted by id -- filtering a sorted array preserves relative
    // order, so the trimmed slice is sorted by id too, and entries 95/96
    // (0-indexed) straddle the initial 96-item window boundary the same
    // way they would against the raw fixture. L18 (docs/code-review-2026-08.md):
    // these two are picked purely POSITIONALLY (not for a verified-unique
    // display name, unlike the hand-picked probes elsewhere in this file),
    // so they're located by `data-testid` (keyed on the guaranteed-unique
    // `id`) rather than by accessible name.
    const lastVisible = trimmedSymbolsFixture[95]!;
    const firstBeyondWindow = trimmedSymbolsFixture[96]!;

    screen.getByTestId(`symbol-option-${lastVisible.id}`).focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId(`symbol-option-${firstBeyondWindow.id}`));
    });
    expect(screen.getAllByRole("option").length).toBeGreaterThan(96);
  });

  it("clicking an icon opens a detail panel with its name/id/category/tags/source/license, and clicking it again closes it", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    // A uniquely-named entry well inside the initial window, with a known
    // category/tags/source/license to assert against.
    const first = firstUniquelyNamed(1)[0]!;
    const option = await screen.findByRole("option", { name: first.name });

    await user.click(option);

    const panel = screen.getByRole("group", { name: `${first.name} details` });
    expect(within(panel).getByText(first.id)).toBeInTheDocument();
    expect(within(panel).getByText(CATEGORY_LABELS[first.category] ?? first.category)).toBeInTheDocument();
    expect(within(panel).getByText(first.tags.join(", "))).toBeInTheDocument();
    expect(within(panel).getByText(`${first.source} · ${first.license}`)).toBeInTheDocument();
    expect(option).toHaveAttribute("aria-selected", "true");

    await user.click(option);
    expect(screen.queryByRole("group", { name: `${first.name} details` })).not.toBeInTheDocument();
    expect(option).toHaveAttribute("aria-selected", "false");
  });

  it("the detail panel's own Close button closes it, and opening a different icon swaps the panel", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    const [first, second] = firstUniquelyNamed(2) as [(typeof trimmedSymbolsFixture)[number], (typeof trimmedSymbolsFixture)[number]];

    await user.click(await screen.findByRole("option", { name: first.name }));
    expect(screen.getByRole("group", { name: `${first.name} details` })).toBeInTheDocument();

    await user.click(await screen.findByRole("option", { name: second.name }));
    expect(screen.queryByRole("group", { name: `${first.name} details` })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: `${second.name} details` })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("group", { name: `${second.name} details` })).not.toBeInTheDocument();
  });

  it("the detail panel is laid out to relocate into a right-hand sidebar on wide (xl) screens", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    const first = firstUniquelyNamed(1)[0]!;

    await user.click(await screen.findByRole("option", { name: first.name }));

    // jsdom doesn't evaluate media queries, so this can't observe the
    // actual reflow -- it proves the SAME node (opened via the ordinary
    // click-to-open flow every other test in this file uses) carries the
    // Tailwind classes that flip it from "inline, above the grid" (its
    // position below `xl`, and in every browser-width-agnostic assertion
    // elsewhere in this file) into an `order-last` sidebar column beside
    // the grid at `xl`+. One panel, not two: the grid+panel wrapper switch
    // from a column to a row at `xl`, and `xl:order-last` reorders the
    // panel within it -- there is no separate sidebar copy to find (which
    // would otherwise leave two `role="group"` nodes with the identical
    // accessible name once a real browser's `xl` media query engaged).
    const panel = screen.getByRole("group", { name: `${first.name} details` });
    expect(panel.className).toContain("xl:order-last");
    expect(panel.className).toContain("xl:w-72");
    expect(panel.parentElement?.className).toContain("xl:flex-row");
  });
});

describe("SymbolBrowser: select mode", () => {
  function Harness({ onSelectSpy, onClearSpy }: { onSelectSpy?: (id: string) => void; onClearSpy?: () => void }) {
    const [selectedId, setSelectedId] = useState<string | null>(null);
    return (
      <SymbolBrowser
        mode="select"
        selectedId={selectedId}
        onSelect={(id) => {
          onSelectSpy?.(id);
          setSelectedId(id);
        }}
        onClear={() => {
          onClearSpy?.();
          setSelectedId(null);
        }}
      />
    );
  }

  it("clicking an option reports it via onSelect and shows the selected chip (no detail panel)", async () => {
    const user = userEvent.setup();
    const onSelectSpy = vi.fn();
    renderWithQueryClient(<Harness onSelectSpy={onSelectSpy} />);

    // "electrical services" (unlike "bolt", pre-regeneration) matches
    // exactly one icon in the trimmed slice -- several new sources add
    // their own "Bolt"-named icons, which would make a single-result query
    // ambiguous.
    await user.type(await screen.findByLabelText("Search symbols"), "electrical services");
    const match = await screen.findByRole("option", { name: "Electrical Services" });
    await user.click(match);

    expect(onSelectSpy).toHaveBeenCalledWith("electrical_services");
    expect(screen.getByText("Electrical Services")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Electrical Services details" })).not.toBeInTheDocument();
  });

  it("the selected chip's Clear button deselects via onClear", async () => {
    const user = userEvent.setup();
    const onClearSpy = vi.fn();
    renderWithQueryClient(<Harness onClearSpy={onClearSpy} />);

    await user.type(await screen.findByLabelText("Search symbols"), "electrical services");
    await user.click(await screen.findByRole("option", { name: "Electrical Services" }));
    await user.click(screen.getByRole("button", { name: "Clear" }));

    expect(onClearSpy).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });
});

describe("SymbolBrowser: H7 regression -- arrow nav at the first option", () => {
  it("ArrowUp on the first rendered option does not grow the window past one WINDOW_SIZE step", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    const initialOptions = screen.getAllByRole("option");
    const initialCount = initialOptions.length;
    expect(initialCount).toBe(96);
    // Roving tabindex's fallback tab stop with nothing marked/selected is
    // the first rendered option (SymbolBrowser's own `activeId` fallback)
    // -- focus it directly, the same node a Tab keypress into the listbox
    // would land on, then walk backward off the front edge. (ArrowLeft on
    // the first option takes the identical `focusByIndex(index - 1)` path
    // -- see handleKeyDown -- so this one direction exercises the fix for
    // both.)
    initialOptions[0]!.focus();

    await user.keyboard("{ArrowUp}");

    // Before the fix (H7, docs/code-review-2026-08.md): focusByIndex(-1)
    // wrapped to `filtered.length - 1` and grew the window in one step to
    // cover it -- i.e. the ENTIRE filtered set (8362 nodes against the
    // real catalog). Growth everywhere else in this component (forward
    // nav past the rendered edge, the IntersectionObserver sentinel) only
    // ever adds one WINDOW_SIZE (96) step at a time, so this must too.
    const afterCount = screen.getAllByRole("option").length;
    expect(afterCount).toBeLessThanOrEqual(initialCount + 96);
    // The trimmed slice (302 entries as the fixture stands) is well past
    // one growth step beyond the initial window (192) -- if the window
    // ever jumped to the full filtered set here, this is what would catch
    // it, independent of exactly how many entries the slice trims to.
    expect(afterCount).toBeLessThan(trimmedSymbolsFixture.length);
  });
});

describe("SymbolBrowser: full-catalog scale (H9)", () => {
  it("windowed grid renders only the initial slice against the real, unsliced 8362-entry catalog", async () => {
    // The one test in this suite that legitimately needs the full fixture
    // (see trimmedSymbolsFixture's own comment in test/msw/handlers.ts) --
    // overrides the default (trimmed) symbolsHandler for this test only. A
    // generous findBy/test timeout is legitimate here specifically because
    // this is deliberately exercising the full 2.1 MB payload's
    // parse/serialize/structural-sharing/render cost that H9 was about in
    // the first place.
    server.use(http.get("/api/symbols", () => HttpResponse.json(symbolsFixture)));
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);

    expect(await screen.findByText(countText(symbolsFixture.length), {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(96);

    // Belt-and-suspenders for H7 at the exact scale the review reproduced
    // it at (96 -> 8362 options after a single ArrowUp on the first
    // option) -- the clamp fix must hold here, not just against the
    // trimmed default slice used by the regression test above.
    screen.getAllByRole("option")[0]!.focus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getAllByRole("option").length).toBeLessThanOrEqual(96 + 96);
  }, 10000);
});

describe("columnCount (L12(a))", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 1 for a null grid element", () => {
    expect(columnCount(null)).toBe(1);
  });

  it("falls back to 1 against a real (unstyled) jsdom element -- jsdom applies no CSS at all, so `getComputedStyle` reports an empty gridTemplateColumns here, and this is the value this component's real jsdom tests (H7 included) depend on to keep their +-1 semantics", () => {
    const grid = document.createElement("div");
    expect(getComputedStyle(grid).gridTemplateColumns).toBe("");
    expect(columnCount(grid)).toBe(1);
  });

  it("also falls back to 1 for the CSS-wide initial value 'none' -- what a real browser reports for grid-template-columns before layout has resolved an auto-fill track list, or for a non-grid element", () => {
    const grid = document.createElement("div");
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      gridTemplateColumns: "none",
    } as CSSStyleDeclaration);

    expect(columnCount(grid)).toBe(1);
  });

  it("counts the resolved space-separated tracks when getComputedStyle reports concrete pixel columns, as a real browser's layout engine would for an auto-fill grid", () => {
    const grid = document.createElement("div");
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      gridTemplateColumns: "72px 72px 72px 72px",
    } as CSSStyleDeclaration);

    expect(columnCount(grid)).toBe(4);
  });

  it("falls back to 1 for an empty gridTemplateColumns string", () => {
    const grid = document.createElement("div");
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      gridTemplateColumns: "",
    } as CSSStyleDeclaration);

    expect(columnCount(grid)).toBe(1);
  });
});
