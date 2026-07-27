import { describe, expect, it } from "vitest";
import { portsCompatible, wouldCreateCycle } from "./graph";
import type { PortDef } from "./api";

const port = (id: string, type: string): PortDef => ({
  id,
  type,
  label: id,
  required: true,
  multiple: false,
  default: false,
});

describe("portsCompatible", () => {
  it("rejects table → figure", () => {
    expect(portsCompatible(port("a", "table"), port("b", "figure"))).toBe(false);
  });
  it("allows any", () => {
    expect(portsCompatible(port("a", "table"), port("b", "any"))).toBe(true);
  });
});

describe("wouldCreateCycle", () => {
  it("rejects C→A when A→B→C exists", () => {
    const edges = [
      { id: "1", source: "A", target: "B" },
      { id: "2", source: "B", target: "C" },
    ] as any;
    expect(wouldCreateCycle(edges, "C", "A")).toBe(true);
    expect(wouldCreateCycle(edges, "A", "C")).toBe(false);
  });
});
