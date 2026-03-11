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
    scored?: number;
    total?: number;
    jobs_found?: number;
  };

  return (
    <div>
      {isActive ? (
        <div className="flex items-center gap-3">
          <div className="h-2 w-32 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full rounded-full bg-blue-600 transition-all"
              style={{
                width: progress?.total
                  ? `${((progress.scored ?? 0) / progress.total) * 100}%`
                  : "30%",
              }}
            />
          </div>
          <span className="text-sm text-gray-600">
            {progress?.phase || run?.status}
            {progress?.scored !== undefined &&
              progress?.total &&
              ` (${progress.scored}/${progress.total})`}
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
