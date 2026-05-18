"use client";

import { usePopover } from "@/lib/use-popover";
import type { EvergreenSignal } from "@/lib/types";

interface Props {
  signal: EvergreenSignal;
  company: string;
}

export default function EvergreenBadge({ signal, company }: Props) {
  const { open, toggle, containerRef } = usePopover<HTMLSpanElement>();

  const sharePct = Math.round(signal.share_180d * 100);
  const share365Pct = signal.share_365d != null ? Math.round(signal.share_365d * 100) : null;
  const snapshotPretty = (() => {
    try {
      return new Date(signal.snapshot_date).toLocaleDateString(undefined, {
        month: "short", day: "numeric", year: "numeric",
      });
    } catch {
      return signal.snapshot_date;
    }
  })();

  return (
    <span ref={containerRef} className="relative inline-block shrink-0">
      <button
        onClick={toggle}
        className="font-mono text-[10px] uppercase tracking-widest text-amber-600 decoration-dotted underline underline-offset-2 cursor-help"
        aria-expanded={open}
        aria-haspopup="true"
      >
        {sharePct}% jobs open 6+ mo
      </button>

      {open && (
        <span
          className="absolute top-full left-0 mt-2 z-50 w-80 max-w-xs bg-white border border-gray-200 shadow-lg rounded-lg p-4 text-sm"
          role="tooltip"
        >
          <p className="font-medium text-gray-900">Long-open job warning</p>

          <div className="mt-3 space-y-1.5 text-gray-700">
            <div className="flex justify-between">
              <span className="text-gray-500">Open 6+ months</span>
              <span className="font-mono">{sharePct}%</span>
            </div>
            {share365Pct !== null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Open 12+ months</span>
                <span className="font-mono">{share365Pct}%</span>
              </div>
            )}
            {signal.total_active != null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Total open jobs</span>
                <span className="font-mono">{signal.total_active}</span>
              </div>
            )}
            {signal.oldest_days != null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Oldest open</span>
                <span className="font-mono">{signal.oldest_days} days</span>
              </div>
            )}
            {signal.mean_days != null && (
              <div className="flex justify-between">
                <span className="text-gray-500">Mean age</span>
                <span className="font-mono">{Math.round(signal.mean_days)} days</span>
              </div>
            )}
          </div>

          <p className="mt-3 text-gray-600 leading-snug">
            Jobs that stay open this long at {company} often indicate a talent
            funnel or recruiting inefficiency — applicants commonly get ghosted.
          </p>

          <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-gray-400">
            via {signal.source} · {snapshotPretty}
          </p>
        </span>
      )}
    </span>
  );
}
