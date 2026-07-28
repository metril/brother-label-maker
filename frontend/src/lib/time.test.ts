import { describe, expect, it } from "vitest";
import { formatAbsoluteTime, formatRelativeTime } from "./time";

const NOW = new Date("2026-07-27T12:00:00.000Z");

describe("formatRelativeTime", () => {
  it("reads 'just now' for anything under a minute old", () => {
    expect(formatRelativeTime("2026-07-27T11:59:31.000Z", NOW)).toBe("just now");
  });

  it("formats minutes ago", () => {
    expect(formatRelativeTime("2026-07-27T11:55:00.000Z", NOW)).toBe("5 minutes ago");
  });

  it("formats hours ago", () => {
    expect(formatRelativeTime("2026-07-27T09:00:00.000Z", NOW)).toBe("3 hours ago");
  });

  it("formats days ago", () => {
    expect(formatRelativeTime("2026-07-24T12:00:00.000Z", NOW)).toBe("3 days ago");
  });

  it("formats a future timestamp as 'in N minutes'", () => {
    expect(formatRelativeTime("2026-07-27T12:10:00.000Z", NOW)).toBe("in 10 minutes");
  });
});

describe("formatAbsoluteTime", () => {
  it("renders a locale date/time string containing the year", () => {
    expect(formatAbsoluteTime("2026-07-27T12:00:00.000Z")).toContain("2026");
  });
});
