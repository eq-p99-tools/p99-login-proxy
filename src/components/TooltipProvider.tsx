import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { computeTooltipPosition } from "./tooltip";

interface TooltipState {
  text: string;
  anchor: DOMRect;
}

function findTooltipTarget(node: EventTarget | null): HTMLElement | null {
  if (!(node instanceof Element)) {
    return null;
  }
  return node.closest<HTMLElement>("[data-tooltip]");
}

function anchorRectFrom(element: HTMLElement): DOMRect {
  return element.getBoundingClientRect();
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TooltipState | null>(null);
  const [coords, setCoords] = useState<{ left: number; top: number } | null>(null);
  const activeTarget = useRef<HTMLElement | null>(null);
  const hideTimer = useRef<number | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!tip || !tipRef.current) {
      setCoords(null);
      return;
    }

    const el = tipRef.current;
    const { width, height } = el.getBoundingClientRect();
    setCoords(
      computeTooltipPosition(
        tip.anchor,
        width,
        height,
        window.innerWidth,
        window.innerHeight,
      ),
    );
  }, [tip]);

  useEffect(() => {
    const clearHideTimer = () => {
      if (hideTimer.current != null) {
        window.clearTimeout(hideTimer.current);
        hideTimer.current = null;
      }
    };

    const hide = () => {
      clearHideTimer();
      activeTarget.current = null;
      setTip(null);
      setCoords(null);
    };

    const showFor = (target: HTMLElement) => {
      const text = target.dataset.tooltip?.trim();
      if (!text) {
        return;
      }
      clearHideTimer();
      activeTarget.current = target;
      setCoords(null);
      setTip({
        text,
        anchor: anchorRectFrom(target),
      });
    };

    const onEnter = (event: Event) => {
      const target = findTooltipTarget(event.target);
      if (!target || target === activeTarget.current) {
        return;
      }
      showFor(target);
    };

    const onLeave = (event: Event) => {
      const from = findTooltipTarget(event.target);
      if (!from || from !== activeTarget.current) {
        return;
      }
      const related = (event as MouseEvent).relatedTarget;
      if (related instanceof Node && from.contains(related)) {
        return;
      }
      clearHideTimer();
      hideTimer.current = window.setTimeout(hide, 80);
    };

    const onViewportChange = () => {
      if (!activeTarget.current) {
        return;
      }
      const target = activeTarget.current;
      const text = target.dataset.tooltip?.trim();
      if (!text) {
        hide();
        return;
      }
      setTip({ text, anchor: anchorRectFrom(target) });
    };

    document.addEventListener("pointerover", onEnter);
    document.addEventListener("pointerout", onLeave);
    // WebView2 on Windows can miss pointer events on tiny SVG targets; mouse events are reliable.
    document.addEventListener("mouseover", onEnter);
    document.addEventListener("mouseout", onLeave);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      document.removeEventListener("pointerover", onEnter);
      document.removeEventListener("pointerout", onLeave);
      document.removeEventListener("mouseover", onEnter);
      document.removeEventListener("mouseout", onLeave);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
      clearHideTimer();
    };
  }, []);

  return (
    <>
      {children}
      {tip
        ? createPortal(
            <div
              ref={tipRef}
              className="app-tooltip"
              role="tooltip"
              data-ready={coords != null ? "true" : "false"}
              style={
                coords
                  ? { left: coords.left, top: coords.top }
                  : { left: 0, top: 0 }
              }
            >
              {tip.text}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
