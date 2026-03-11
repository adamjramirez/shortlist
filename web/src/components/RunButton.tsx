"use client";

import { useState, useEffect, useRef } from "react";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";

interface Props {
  onComplete?: () => void;
  onProgress?: () => void;
}

export default function RunButton({ onComplete, onProgress }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const isActive = run && (run.status === "pending" || run.status === "running");

  useEffect(() => {
    // Check for existing active run on mount
    runsApi.list().then((runs) => {
      const active = runs.find(
        (r) => r.status === "pending" || r.status === "running",
      );
      if (active) setRun(active);
    });
  }, []);

  const runId = run?.id;

  useEffect(() => {
    if (!isActive || !runId) return;

    let lastMatches = 0;
    intervalRef.current = setInterval(async () => {
      try {
        const updated = await runsApi.get(runId);
        setRun(updated);

        // Refresh job list when new matches arrive
        const matches = (updated.progress as Record<string, number>)?.matches ?? 0;
        if (matches > lastMatches) {
          lastMatches = matches;
          onProgress?.();
        }

        if (updated.status !== "pending" && updated.status !== "running") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          if (updated.status === "completed") onComplete?.();
        }
      } catch {
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }, 3000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [runId, isActive, onComplete, onProgress]);

  const handleRun = async () => {
    setError("");
    try {
      const newRun = await runsApi.create();
      setRun(newRun);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
    }
  };

  const handleCancel = async () => {
    if (!run) return;
    try {
      const updated = await runsApi.cancel(run.id);
      setRun(updated);
      if (intervalRef.current) clearInterval(intervalRef.current);
    } catch {
      // If cancel fails, force-clear locally so user isn't stuck
      setRun(null);
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
  };

  const progress = run?.progress as {
    phase?: string;
    detail?: string;
    scored?: number;
    total?: number;
    jobs_found?: number;
    eta_seconds?: number;
    elapsed_seconds?: number;
  };

  const phaseLabels: Record<string, string> = {
    starting: "Starting up…",
    collecting: "Searching job boards…",
    fetching: "Fetching job details…",
    "saving results": "Saving results…",
    done: "Complete!",
  };

  const phaseLabel =
    progress?.detail ||
    phaseLabels[progress?.phase || ""] ||
    progress?.phase ||
    run?.status ||
    "";

  function formatEta(seconds: number): string {
    if (seconds <= 10) return "almost done";
    if (seconds < 60) return `~${Math.ceil(seconds / 10) * 10}s left`;
    const mins = Math.ceil(seconds / 60);
    return `~${mins} min left`;
  }

  // Overall progress fraction for the bar
  const TOTAL_SECONDS = 195; // sum of phase estimates
  const etaSeconds = progress?.eta_seconds;
  const elapsedSeconds = progress?.elapsed_seconds ?? 0;
  const fraction =
    etaSeconds !== undefined && etaSeconds + elapsedSeconds > 0
      ? Math.min(0.95, elapsedSeconds / (elapsedSeconds + etaSeconds))
      : undefined;

  return (
    <div>
      {isActive ? (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <svg
              className="h-4 w-4 shrink-0 animate-spin text-blue-600"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
              />
            </svg>
            <span className="text-sm text-gray-600">
              {phaseLabel}
              {progress?.scored !== undefined &&
                progress?.total !== undefined &&
                progress.total > 0 &&
                ` (${progress.scored}/${progress.total})`}
            </span>
          </div>
          {/* Progress bar */}
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full rounded-full bg-blue-600 transition-all duration-700 ease-out"
              style={{ width: `${fraction !== undefined ? fraction * 100 : 5}%` }}
            />
          </div>
          {/* ETA + cancel */}
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-400">
              {etaSeconds !== undefined && etaSeconds > 0
                ? formatEta(etaSeconds)
                : elapsedSeconds > 0
                  ? "finishing up…"
                  : "estimating time…"}
            </p>
            <button
              onClick={handleCancel}
              className="text-xs text-gray-400 hover:text-red-500"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            onClick={handleRun}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Run now
          </button>
          <span className="text-xs text-gray-400">3/hour · 10/day</span>
        </div>
      )}
      {run?.status === "failed" && (
        <p className="mt-2 text-sm text-red-600">
          Run failed: {run.error || "Unknown error"}
        </p>
      )}
      {run?.status === "cancelled" && (
        <p className="mt-2 text-sm text-gray-500">
          Run cancelled
        </p>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
