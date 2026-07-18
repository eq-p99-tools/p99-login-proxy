import { describe, expect, it } from "vitest";

import { computeTooltipPosition } from "./tooltip";

const anchor = {
  left: 100,
  top: 400,
  right: 200,
  bottom: 420,
  width: 100,
  height: 20,
};

describe("computeTooltipPosition", () => {
  it("places tooltip below the anchor by default", () => {
    const pos = computeTooltipPosition(anchor, 120, 40, 800, 600);
    expect(pos.top).toBe(426);
    expect(pos.left).toBe(150);
  });

  it("flips above when there is not enough room below", () => {
    const lowAnchor = { ...anchor, top: 560, bottom: 580 };
    const pos = computeTooltipPosition(lowAnchor, 120, 40, 800, 600);
    expect(pos.top).toBe(514);
  });

  it("clamps horizontal position near the right edge", () => {
    const rightAnchor = { left: 760, top: 100, right: 790, bottom: 120, width: 30, height: 20 };
    const pos = computeTooltipPosition(rightAnchor, 120, 40, 800, 600);
    expect(pos.left).toBeLessThanOrEqual(800 - 8 - 60);
    expect(pos.left).toBeGreaterThan(120);
  });

  it("keeps tooltip inside the viewport vertically", () => {
    const pos = computeTooltipPosition(anchor, 120, 500, 800, 600);
    expect(pos.top).toBeGreaterThanOrEqual(8);
    expect(pos.top + 500).toBeLessThanOrEqual(600 - 8);
  });
});
