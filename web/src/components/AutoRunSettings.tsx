"use client";

import { useEffect, useState } from "react";
import type { AutoRunConfig } from "@/lib/types";

const INTERVAL_OPTIONS = [
  { value: 6, label: "Every 6 hours" },
  { value: 12, label: "Every 12 hours" },
  { value: 24, label: "Every 24 hours" },
  { value: 48, label: "Every 48 hours" },
];

const selectClass =
  "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function formatCountdown(nextRunAt: string | null): string {
  if (!nextRunAt) return "";
  const diff = new Date(nextRunAt).getTime() - Date.now();
  if (diff <= 0) return "any moment";
  const totalMin = Math.floor(diff / 60_000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

interface Props {
  autoRun: AutoRunConfig;
  onChange: (update: Partial<Pick<AutoRunConfig, "enabled" | "interval_h">>) => void;
}

export default function AutoRunSettings({ autoRun, onChange }: Props) {
  const [countdown, setCountdown] = useState(() => formatCountdown(autoRun.next_run_at));

  // Refresh countdown every minute
  useEffect(() => {
    setCountdown(formatCountdown(autoRun.next_run_at));
    const id = setInterval(
      () => setCountdown(formatCountdown(autoRun.next_run_at)),
      60_000,
    );
    return () => clearInterval(id);
  }, [autoRun.next_run_at]);

  const isPaused = !autoRun.enabled && autoRun.consecutive_failures >= 5;
  const hasFailures = autoRun.consecutive_failures > 0 && autoRun.enabled;

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Run automatically on a schedule so new jobs appear in your inbox without manual action.
      </p>

      {/* Paused by scheduler warning */}
      {isPaused && (
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
          <span className="mt-0.5 text-red-500">✕</span>
          <div className="flex-1 text-sm text-red-700">
            Auto-run paused after 5 consecutive failures.{" "}
            <button
              onClick={() => onChange({ enabled: true })}
              className="font-medium underline hover:no-underline"
            >
              Re-enable
            </button>
          </div>
        </div>
      )}

      {/* Failure warning (while still enabled) */}
      {hasFailures && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <span className="mt-0.5 text-amber-500">⚠</span>
          <p className="text-sm text-amber-700">
            Last {autoRun.consecutive_failures} run
            {autoRun.consecutive_failures > 1 ? "s" : ""} failed. Check your API key and rate
            limits.
          </p>
        </div>
      )}

      {/* Toggle + interval row */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Toggle */}
        <button
          type="button"
          role="switch"
          aria-checked={autoRun.enabled}
          onClick={() => onChange({ enabled: !autoRun.enabled })}
          className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${
            autoRun.enabled ? "bg-emerald-600" : "bg-gray-200"
          }`}
        >
          <span
            className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
              autoRun.enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </button>
        <span className="text-sm font-medium text-gray-700">
          {autoRun.enabled ? "On" : "Off"}
        </span>

        {/* Interval selector */}
        {autoRun.enabled && (
          <select
            value={autoRun.interval_h}
            onChange={(e) => onChange({ interval_h: Number(e.target.value) })}
            className={selectClass}
          >
            {INTERVAL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Next run countdown */}
      {autoRun.enabled && autoRun.next_run_at && (
        <p className="text-sm text-gray-500">
          Next run: <span className="font-medium text-gray-700">in {countdown}</span>
        </p>
      )}
    </div>
  );
}
