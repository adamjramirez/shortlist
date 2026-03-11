"use client";

import { useState, useEffect, useRef } from "react";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";

interface Props {
  onComplete?: () => void;
}

export default function RunButton({ onComplete }: Props) {
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

    intervalRef.current = setInterval(async () => {
      try {
        const updated = await runsApi.get(runId);
        setRun(updated);
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
  }, [runId, isActive, onComplete]);

  const handleRun = async () => {
    setError("");
    try {
      const newRun = await runsApi.create();
      setRun(newRun);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
    }
  };

  const progress = run?.progress as {
    phase?: string;
    detail?: string;
    scored?: number;
    total?: number;
    jobs_found?: number;
  };

  const phaseLabels: Record<string, string> = {
    starting: "Starting up…",
    collecting: "Scraping job boards…",
    "saving results": "Saving results…",
    done: "Complete!",
  };

  const phaseLabel = progress?.detail || phaseLabels[progress?.phase || ""] || progress?.phase || run?.status || "";

  return (
    <div>
      {isActive ? (
        <div className="flex items-center gap-3">
          <svg
            className="h-4 w-4 animate-spin text-blue-600"
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
              progress?.total &&
              ` (${progress.scored}/${progress.total})`}
            {progress?.jobs_found !== undefined &&
              !progress?.total &&
              ` — ${progress.jobs_found} jobs found`}
          </span>
        </div>
      ) : (
        <button
          onClick={handleRun}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Run now
        </button>
      )}
      {run?.status === "failed" && (
        <p className="mt-2 text-sm text-red-600">
          Run failed: {run.error || "Unknown error"}
        </p>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
