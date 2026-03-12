"use client";

import { useState, useEffect, useRef } from "react";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";

interface Props {
  onComplete?: () => void;
  onProgress?: () => void;
}

interface Step {
  key: string;
  label: string;
}

export default function RunButton({ onComplete, onProgress }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const isActive = run && (run.status === "pending" || run.status === "running");

  useEffect(() => {
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
      setRun(null);
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
  };

  const progress = run?.progress as {
    phase?: string;
    detail?: string;
    step?: string;
    steps?: Step[];
    scored?: number;
    total?: number;
    matches?: number;
    elapsed_seconds?: number;
  };

  // Fallback matches STEPS in worker.py — used before first progress update arrives
  const steps: Step[] = progress?.steps ?? [
    { key: "search", label: "Searching job boards" },
    { key: "score", label: "AI scoring" },
    { key: "research", label: "Company research" },
    { key: "done", label: "Complete" },
  ];

  const currentStep = progress?.step || "search";
  const currentStepIdx = steps.findIndex((s) => s.key === currentStep);
  const matches = progress?.matches ?? 0;
  const elapsed = progress?.elapsed_seconds ?? 0;

  function formatElapsed(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  return (
    <div>
      {isActive ? (
        <div className="space-y-3">
          {/* Step indicators */}
          <div className="flex items-center gap-1">
            {steps.filter(s => s.key !== "done").map((step, i) => {
              const isComplete = i < currentStepIdx;
              const isCurrent = i === currentStepIdx;
              return (
                <div key={step.key} className="flex items-center gap-1">
                  {i > 0 && (
                    <div className={`h-px w-4 ${isComplete ? "bg-blue-500" : "bg-gray-200"}`} />
                  )}
                  <div className="flex items-center gap-1.5">
                    <div
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                        isComplete
                          ? "bg-blue-600 text-white"
                          : isCurrent
                            ? "border-2 border-blue-600 text-blue-600"
                            : "border border-gray-300 text-gray-400"
                      }`}
                    >
                      {isComplete ? "✓" : i + 1}
                    </div>
                    <span
                      className={`text-xs ${
                        isCurrent ? "font-medium text-gray-900" : "text-gray-400"
                      }`}
                    >
                      {step.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Current activity */}
          <div className="flex items-center gap-2">
            <svg
              className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600"
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
              {progress?.detail || steps[currentStepIdx]?.label || "Working…"}
            </span>
          </div>

          {/* Stats + cancel */}
          <div className="flex items-center justify-between text-xs text-gray-400">
            <div className="flex gap-3">
              {matches > 0 && (
                <span className="font-medium text-blue-600">{matches} matches</span>
              )}
              {elapsed > 0 && <span>{formatElapsed(elapsed)}</span>}
            </div>
            <button
              onClick={handleCancel}
              className="text-gray-400 hover:text-red-500"
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
        <p className="mt-2 text-sm text-gray-500">Run cancelled</p>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
