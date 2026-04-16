"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { track } from "@/lib/analytics";

interface Props {
  jobId: number;
  value: string;
  confidence: string | null;
  basis: string | null;
}

export default function SalaryEstimate({ jobId, value, confidence, basis }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);

  // Close on click-outside or Escape
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

  function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    const next = !open;
    setOpen(next);
    if (next) {
      track.salaryEstimateExpanded(jobId, confidence);
    }
  }

  const confidenceValue = confidence ?? "unknown";
  const confidenceLevel =
    confidence === "high" ? 3 : confidence === "medium" ? 2 : confidence === "low" ? 1 : 0;

  return (
    <span ref={containerRef} className="relative inline-block shrink-0">
      <button
        onClick={handleToggle}
        className="font-mono text-sm font-normal text-gray-500 decoration-dotted underline underline-offset-2 cursor-help"
        aria-expanded={open}
        aria-haspopup="true"
      >
        ~{value}
      </button>

      {open && (
        <span
          className="absolute top-full right-0 mt-2 z-50 w-72 max-w-xs bg-white border border-gray-200 shadow-lg rounded-lg p-4 text-sm"
          role="tooltip"
        >
          <p className="font-medium text-gray-900">Estimated — not in the job posting</p>

          <div className="mt-3 flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 shrink-0">
              Confidence
            </span>
            <span className="flex gap-1" aria-label={`Confidence: ${confidenceValue}`}>
              {[1, 2, 3].map((i) => (
                <span
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full ${
                    i <= confidenceLevel ? "bg-gray-900" : "bg-gray-200"
                  }`}
                />
              ))}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-gray-900">
              {confidenceValue}
            </span>
          </div>

          {basis && (
            <p className="mt-2 text-gray-600 leading-snug">{basis}</p>
          )}

          <Link
            href="/about/estimates"
            className="mt-3 inline-block text-emerald-600 underline underline-offset-2 hover:text-emerald-700 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            How we estimate →
          </Link>
        </span>
      )}
    </span>
  );
}
