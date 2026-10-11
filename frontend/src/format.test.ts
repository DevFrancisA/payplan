import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, percentOf, todayIso } from "./format";

describe("format", () => {
  it("formats decimal strings as currency", () => {
    expect(formatMoney("1200.00")).toBe("$1,200.00");
    expect(formatMoney("0.10")).toBe("$0.10");
  });

  it("formats calendar dates without timezone drift", () => {
    expect(formatDate("2026-10-01")).toBe("Oct 1, 2026");
    expect(formatDate("2028-02-29")).toBe("Feb 29, 2028");
  });

  it("computes progress percentages in cents", () => {
    expect(percentOf("300.00", "1200.00")).toBe(25);
    expect(percentOf("0.00", "0.00")).toBe(0);
  });

  it("returns today's local date", () => {
    expect(todayIso(new Date(2026, 9, 11, 23, 30))).toBe("2026-10-11");
  });
});
