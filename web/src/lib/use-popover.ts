"use client";

import { useState, useRef, useEffect, useCallback } from "react";

/** Click-toggle popover state with click-outside + Escape close.
 *  Attach `containerRef` to the wrapping element that includes BOTH the
 *  trigger and the panel — clicks inside that wrapper won't close it.
 */
export function usePopover<T extends HTMLElement = HTMLElement>() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<T>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const toggle = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation();
    setOpen((prev) => !prev);
  }, []);

  return { open, setOpen, toggle, containerRef };
}
