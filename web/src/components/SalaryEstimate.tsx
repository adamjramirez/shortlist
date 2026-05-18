"use client";

import Link from "next/link";
import { track } from "@/lib/analytics";
import { usePopover } from "@/lib/use-popover";

interface Props {
  jobId: number;
  value: string;
  confidence: string | null;
  basis: string | null;
}

export default function SalaryEstimate({ jobId, value, confidence, basis }: Props) {
  const { open, toggle, containerRef } = usePopover<HTMLSpanElement>();

  function handleToggle(e: React.MouseEvent) {
    toggle(e);
    if (!open) {
      // open is the pre-toggle value, so !open === "we're about to open"
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
