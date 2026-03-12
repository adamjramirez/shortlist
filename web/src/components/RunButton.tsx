"use client";

import { useState, useEffect, useRef } from "react";
import { runs as runsApi } from "@/lib/api";
import { track } from "@/lib/analytics";
import type { Run } from "@/lib/types";

interface Props {
  onComplete?: () => void;
  onProgress?: () => void;
  onActiveChange?: (active: boolean) => void;
}

interface SourceState {
  status: string;
  collected?: number;
  filtered?: number;
  matches?: number;
  scored?: number;
  error?: string;
  elapsed?: number;
  substatus?: string;
  fetch_progress?: string;
}

const SOURCE_LABELS: Record<string, string> = {
  hn: "Hacker News",
  linkedin: "LinkedIn",
  nextplay: "NextPlay",
};

function SourceRow({ name, state }: { name: string; state: SourceState }) {
  const label = SOURCE_LABELS[name] || name;

  // Status icon
  let icon: string;
  let color: string;
  switch (state.status) {
    case "done":
      icon = "✓";
      color = "text-green-600";
      break;
    case "failed":
      icon = "✗";
      color = "text-red-500";
      break;
    case "waiting":
    case "skipped":
      icon = "○";
      color = "text-gray-300";
      break;
    default: // searching, filtering, scoring, fetching
      icon = "◌";
      color = "text-blue-500 animate-pulse";
  }

  function fmtTime(s: number): string {
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
  }

  // Status detail
  let detail = "";
  if (state.status === "searching") {
    detail = state.substatus || "searching…";
  } else if (state.status === "filtering") {
    detail = `${state.collected} found → filtering…`;
  } else if (state.status === "fetching") {
    detail = state.fetch_progress ? `fetching descriptions (${state.fetch_progress})…` : "fetching descriptions…";
  } else if (state.status === "scoring") {
    detail = `scoring ${state.filtered ?? "?"} jobs…`;
  } else if (state.status === "done") {
    const parts: string[] = [];
    if (state.collected !== undefined) parts.push(`${state.collected} found`);
    if (state.filtered !== undefined) parts.push(`${state.filtered} passed`);
    if (state.matches !== undefined) parts.push(`${state.matches} matches`);
    detail = parts.join(" → ");
  } else if (state.status === "failed") {
    detail = state.error || "failed";
  }

  const elapsed = state.elapsed && state.elapsed > 0 && state.status !== "waiting" ? fmtTime(state.elapsed) : "";

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`text-xs font-bold ${color}`}>{icon}</span>
      <span className="font-medium text-gray-700 w-24">{label}</span>
      <span className="text-gray-500 text-xs flex-1">{detail}</span>
      {elapsed && <span className="text-gray-300 text-xs tabular-nums">{elapsed}</span>}
    </div>
  );
}

export default function RunButton({ onComplete, onProgress, onActiveChange }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const isActive = run && (run.status === "pending" || run.status === "running");

  useEffect(() => {
    onActiveChange?.(!!isActive);
  }, [isActive, onActiveChange]);

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

    let lastSourceStates = "";
    intervalRef.current = setInterval(async () => {
      try {
        const updated = await runsApi.get(runId);
        setRun(updated);

        // Refresh job list when any source finishes scoring
        const sources = (updated.progress as Record<string, unknown>)?.sources;
        const stateKey = sources ? JSON.stringify(sources) : "";
        if (stateKey !== lastSourceStates) {
          lastSourceStates = stateKey;
          onProgress?.();
        }

        if (updated.status !== "pending" && updated.status !== "running") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          if (updated.status === "completed") {
            track.runCompleted((updated.progress?.matches as number) ?? 0);
            onComplete?.();
          }
        }
      } catch {
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }, 2000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [runId, isActive, onComplete, onProgress]);

  const handleRun = async () => {
    setError("");
    try {
      const newRun = await runsApi.create();
      setRun(newRun);
      track.runStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
    }
  };

  const handleCancel = async () => {
    if (!run) return;
    try {
      const updated = await runsApi.cancel(run.id);
      setRun(updated);
      track.runCancelled();
      if (intervalRef.current) clearInterval(intervalRef.current);
    } catch {
      setRun(null);
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
  };

  const progress = run?.progress as {
    phase?: string;
    detail?: string;
    sources?: Record<string, SourceState>;
    matches?: number;
    elapsed_seconds?: number;
    http_status?: string;
  };

  const sources = progress?.sources;
  const matches = progress?.matches ?? 0;
  const elapsed = progress?.elapsed_seconds ?? 0;
  const phase = progress?.phase;

  // Enrichment phase (after all sources done)
  const isEnriching = phase === "enriching";
  const allSourcesDone = sources && Object.values(sources).every(
    (s) => s.status === "done" || s.status === "failed" || s.status === "skipped"
  );

  function formatElapsed(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  return (
    <div>
      {isActive ? (
        <div className="space-y-2">
          {/* Per-source progress */}
          {sources ? (
            <div className="space-y-1">
              {Object.entries(sources).map(([name, state]) => (
                <SourceRow key={name} name={name} state={state} />
              ))}
              {allSourcesDone && (
                <div className="flex items-center gap-2 text-sm mt-1">
                  <span className={`text-xs font-bold ${isEnriching ? "text-blue-500 animate-pulse" : "text-gray-300"}`}>
                    {isEnriching ? "◌" : "○"}
                  </span>
                  <span className="font-medium text-gray-700 w-24">Research</span>
                  <span className="text-gray-500 text-xs">
                    {isEnriching ? (progress?.detail || "researching companies…") : "waiting…"}
                  </span>
                </div>
              )}
            </div>
          ) : (
            // Before first progress update
            <div className="flex items-center gap-2">
              <svg className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              <span className="text-sm text-gray-600">Starting up…</span>
            </div>
          )}

          {/* Rate limit warning */}
          {progress?.http_status && (
            <div className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1">
              ⏳ {progress.http_status}
            </div>
          )}

          {/* Stats + cancel */}
          <div className="flex items-center justify-between text-xs text-gray-400 pt-1 border-t border-gray-100">
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
