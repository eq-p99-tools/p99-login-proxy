/** Props for custom multiline tooltips (native `title` collapses newlines in WebView). */
export const TOOLTIP_AFFIRMATIVE = "\u2705"; // ✅
export const TOOLTIP_NEGATIVE = "\u274C"; // ❌

export function tooltipProps(text: string | undefined): { "data-tooltip"?: string } {
  if (!text) {
    return {};
  }
  return { "data-tooltip": text };
}

export interface TooltipAnchorRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

const TOOLTIP_MARGIN = 8;
const TOOLTIP_GAP = 6;

/** Keep tooltip fully inside the viewport; flip above the anchor when needed. */
export function computeTooltipPosition(
  anchor: TooltipAnchorRect,
  tipWidth: number,
  tipHeight: number,
  viewportWidth: number,
  viewportHeight: number,
): { left: number; top: number } {
  const centerX = anchor.left + anchor.width / 2;
  const spaceBelow = viewportHeight - anchor.bottom - TOOLTIP_GAP - TOOLTIP_MARGIN;
  const spaceAbove = anchor.top - TOOLTIP_GAP - TOOLTIP_MARGIN;

  let top =
    tipHeight > spaceBelow && spaceAbove > spaceBelow
      ? anchor.top - TOOLTIP_GAP - tipHeight
      : anchor.bottom + TOOLTIP_GAP;

  top = Math.max(TOOLTIP_MARGIN, Math.min(top, viewportHeight - tipHeight - TOOLTIP_MARGIN));

  const halfW = tipWidth / 2;
  const maxCenter = viewportWidth - TOOLTIP_MARGIN - halfW;
  const minCenter = TOOLTIP_MARGIN + halfW;
  const left = halfW > maxCenter ? viewportWidth / 2 : Math.max(minCenter, Math.min(centerX, maxCenter));

  return { left, top };
}
