import { buildUrl } from "../api/client";
import { BY_STATUS, STATUSES } from "../test/fixtures";
import { fmtInt } from "./format";
import { c4cTicketUrl, documentHref } from "./links";
import { groupByPhase, NO_STATUS_LABEL, OUTSIDE_LABEL, phases, progressOf, toneOf } from "./status";
import { OTHER_LABEL, slotOf, techShares } from "./technology";

describe("status", () => {
  it("lists the process phases in catalogue order", () => {
    expect(phases(STATUSES)).toEqual(["Eingang", "Prüfung", "Reservierung & Umsetzung"]);
  });

  it("derives the process step from the in-process statuses", () => {
    expect(progressOf("Netztechnische Prüfung positiv (intern)", STATUSES)).toEqual({ step: 3, total: 4 });
    expect(progressOf("Offen", STATUSES)).toEqual({ step: null, total: 4 });
    expect(progressOf(null, STATUSES)).toEqual({ step: null, total: 4 });
  });

  it("colours statuses by phase, Eingestellt red, everything else neutral", () => {
    expect(toneOf("Standortanfrage eingegangen", STATUSES)).toBe("early");
    expect(toneOf("Netztechnische Prüfung positiv (intern)", STATUSES)).toBe("check");
    expect(toneOf("Reservierungsangebot angenommen", STATUSES)).toBe("res");
    expect(toneOf("Eingestellt", STATUSES)).toBe("stop");
    expect(toneOf("Offen", STATUSES)).toBe("neutral");
    expect(toneOf("Unbekannt", STATUSES)).toBe("neutral");
  });

  it("groups the aggregate by phase, keeps empty steps and collects unknown statuses outside", () => {
    const groups = groupByPhase([...BY_STATUS.items, { key: null, count: 3, sum_max_p: 0 }], STATUSES);
    expect(groups.map((g) => [g.label, g.count])).toEqual([
      ["Eingang", 2],
      ["Prüfung", 0],
      ["Reservierung & Umsetzung", 0],
      [OUTSIDE_LABEL, 5],
    ]);
    expect(groups[0].rows.map((r) => r.count)).toEqual([0, 2]);
    expect(groups[3].rows.map((r) => r.label)).toEqual(["Offen", "Eingestellt", "Neuer Status", NO_STATUS_LABEL]);
    expect(groups[3].outside).toBe(true);
  });
});

describe("technology", () => {
  const items = ["A", "B", "C", "D", "E", "F", "G"].map((key, i) => ({ key, count: 1, sum_max_p: 70 - i * 10 }));

  it("keeps the five largest by MW and sums the rest", () => {
    const shares = techShares(items);
    expect(shares.map((s) => s.label)).toEqual(["A", "B", "C", "D", "E", OTHER_LABEL]);
    expect(shares.at(-1)).toMatchObject({ slot: 0, count: 2, sumMaxP: 20 + 10 });
    expect(shares.reduce((n, s) => n + s.share, 0)).toBeCloseTo(1);
  });

  it("colours a multi-valued technology by its first value", () => {
    const shares = techShares(items);
    expect(slotOf("B | A", shares)).toBe(2);
    expect(slotOf("G", shares)).toBe(0);
    expect(slotOf(null, shares)).toBe(0);
  });

  it("handles an empty aggregate", () => {
    expect(techShares([])).toEqual([]);
  });
});

describe("links", () => {
  it("builds the C4C link from the configured template", () => {
    expect(c4cTicketUrl(123, "https://c4c.example/ticket/{id}/view")).toBe("https://c4c.example/ticket/123/view");
    expect(c4cTicketUrl(123, "https://c4c.example/ticket/")).toBe("https://c4c.example/ticket/123");
    expect(c4cTicketUrl(123, "")).toBeNull();
    expect(c4cTicketUrl(null, "https://c4c.example/{id}")).toBeNull();
  });

  it("links only real URLs as documents", () => {
    expect(documentHref("https://elo.example/doc/1")).toBe("https://elo.example/doc/1");
    expect(documentHref("Referenz-0001")).toBeNull();
    expect(documentHref(null)).toBeNull();
  });
});

describe("api", () => {
  it("repeats list parameters and drops empty ones", () => {
    expect(buildUrl("/x", { exclude_status: ["Eingestellt", "Offen"], q: "", split_multi: true })).toBe(
      "/api/v1/x?exclude_status=Eingestellt&exclude_status=Offen&split_multi=true",
    );
  });
});

describe("format", () => {
  it("formats numbers the German way", () => {
    expect(fmtInt(52005)).toBe("52.005");
  });
});
