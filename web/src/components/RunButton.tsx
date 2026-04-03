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

  let statusColor: string;
  let statusIcon: React.ReactNode;
  switch (state.status) {
    case "done":
      statusColor = "text-emerald-600";
      statusIcon = (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      );
      break;
    case "failed":
      statusColor = "text-red-500";
      statusIcon = (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      );
      break;
    case "waiting":
    case "skipped":
      statusColor = "text-gray-300";
      statusIcon = <span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />;
      break;
    default:
      statusColor = "text-emerald-500";
      statusIcon = <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse inline-block" />;
  }

  function fmtTime(s: number): string {
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
  }

  let detail = "";
  if (state.status === "searching") {
    detail = state.substatus || "searching...";
  } else if (state.status === "filtering") {
    detail = `${state.collected} found, filtering...`;
  } else if (state.status === "fetching") {
    detail = state.fetch_progress ? `fetching descriptions (${state.fetch_progress})...` : "fetching descriptions...";
  } else if (state.status === "scoring") {
    detail = `scoring ${state.filtered ?? "?"} jobs...`;
  } else if (state.status === "done") {
    const parts: string[] = [];
    if (state.collected !== undefined) parts.push(`${state.collected} found`);
    if (state.filtered !== undefined) parts.push(`${state.filtered} passed`);
    if (state.matches !== undefined) parts.push(`${state.matches} matches`);
    detail = parts.join(" / ");
  } else if (state.status === "failed") {
    detail = state.error || "failed";
  }

  const elapsed = state.elapsed && state.elapsed > 0 && state.status !== "waiting" ? fmtTime(state.elapsed) : "";

  return (
    <div className="flex items-center gap-3 text-sm py-1">
      <span className={`shrink-0 flex items-center justify-center w-4 ${statusColor}`}>{statusIcon}</span>
      <span className="font-medium text-gray-900 w-24 shrink-0">{label}</span>
      <span className="text-gray-500 text-xs flex-1 font-mono">{detail}</span>
      {elapsed && <span className="text-gray-400 text-xs font-mono tabular-nums">{elapsed}</span>}
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
      if (active) {
        setRun(active);
      } else if (runs.length > 0 && runs[0].status === "completed") {
        const firedKey = `run_completed_${runs[0].id}`;
        if (!sessionStorage.getItem(firedKey)) {
          track.runCompleted((runs[0].progress?.matches as number) ?? 0);
          sessionStorage.setItem(firedKey, "1");
        }
      }
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
      } catch (err) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        const msg = err instanceof Error ? err.message : "Polling failed";
        track.runFailed(msg);
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
      const msg = err instanceof Error ? err.message : "Failed to start run";
      setError(msg);
      track.runFailed(msg);
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
          {sources ? (
            <div>
              {Object.entries(sources).map(([name, state]) => (
                <SourceRow key={name} name={name} state={state} />
              ))}
              {allSourcesDone && (
                <div className="flex items-center gap-3 text-sm py-1">
                  <span className="shrink-0 flex items-center justify-center w-4">
                    {isEnriching
                      ? <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse inline-block" />
                      : <span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />
                    }
                  </span>
                  <span className="font-medium text-gray-900 w-24">Research</span>
                  <span className="text-gray-500 text-xs font-mono">
                    {isEnriching ? (progress?.detail || "researching companies...") : "waiting..."}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-sm text-gray-600">Starting up...</span>
            </div>
          )}

          {progress?.http_status && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5 font-mono">
              {progress.http_status}
            </div>
          )}

          <div className="flex items-center justify-between text-xs text-gray-400 pt-2 border-t border-gray-200/60">
            <div className="flex gap-3 font-mono">
              {matches > 0 && (
                <span className="font-semibold text-emerald-600">{matches} matches</span>
              )}
              {elapsed > 0 && <span>{formatElapsed(elapsed)}</span>}
            </div>
            <button
              onClick={handleCancel}
              className="text-gray-400 hover:text-red-500 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            onClick={handleRun}
            className="rounded-full bg-gray-900 px-6 py-2.5 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
          >
            Run now
          </button>
          <span className="font-mono text-xs text-gray-400">3/hour</span>
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
