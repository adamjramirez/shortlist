"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRequireAuth } from "@/lib/use-require-auth";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";
import { HistorySkeleton } from "@/components/Skeleton";

/* ── Status dot color ── */
function dotColor(status: string): string {
  switch (status) {
    case "completed": return "bg-emerald-600";
    case "running":
    case "pending": return "bg-gray-400 animate-pulse";
    case "cancelled": return "bg-gray-300";
    case "failed": return "bg-red-500";
    default: return "bg-gray-300";
  }
}

/* ── Relative date: "Today at 2:15 PM", "Yesterday at 9:00 AM", "Mar 28 at 4:30 PM" ── */
function formatDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  if (isToday) return `Today at ${time}`;
  if (isYesterday) return `Yesterday at ${time}`;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} at ${time}`;
}

/* ── Duration: "3m 42s", "12s", "1h 5m" ── */
function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "—";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (ms < 0) return "—";
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
}

/* ── Stats line from progress ── */
interface SourceStats {
  status?: string;
  collected?: number;
  filtered?: number;
  scored?: number;
  matches?: number;
}

function statsLine(progress: Record<string, unknown>): string {
  const parts: string[] = [];
  const sources = progress.sources as Record<string, SourceStats> | undefined;

  // jobs_collected is set at top level on completion; during run, sum from sources
  let totalCollected = progress.jobs_collected as number | undefined;
  // totalScored is never set at top level — always sum from per-source data
  let totalScored = 0;
  if (sources) {
    if (!totalCollected) {
      totalCollected = 0;
      for (const s of Object.values(sources)) totalCollected += s.collected ?? 0;
    }
    for (const s of Object.values(sources)) totalScored += s.scored ?? 0;
  }

  if (totalCollected) parts.push(`${totalCollected} collected`);
  if (totalScored) parts.push(`${totalScored} scored`);

  const matches = progress.matches as number | undefined;
  if (matches !== undefined) parts.push(`${matches} match${matches === 1 ? "" : "es"}`);

  return parts.length > 0 ? parts.join(" → ") : "—";
}

/* ── Per-source breakdown ── */
function SourceBreakdown({ sources }: { sources: Record<string, SourceStats> }) {
  const entries = Object.entries(sources).filter(
    ([, s]) => s.collected !== undefined || s.matches !== undefined
  );
  if (entries.length === 0) return null;

  return (
    <div className="mt-3 ml-1 space-y-1">
      {entries.map(([name, s]) => {
        const parts: string[] = [];
        if (s.collected) parts.push(`${s.collected} collected`);
        if (s.scored) parts.push(`${s.scored} scored`);
        parts.push(`${s.matches ?? 0} match${(s.matches ?? 0) === 1 ? "" : "es"}`);
        return (
          <div key={name} className="flex items-baseline gap-3 font-mono text-xs">
            <span className="text-gray-400 w-20 shrink-0">{name}</span>
            <span className="text-gray-500">{parts.join(" → ")}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function HistoryPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [runList, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    if (authLoading || !user) return;
    runsApi
      .list()
      .then(setRuns)
      .finally(() => setLoading(false));
  }, [user, authLoading]);

  if (loading) return <HistorySkeleton />;

  const hasSources = (run: Run) => {
    const sources = run.progress?.sources as Record<string, SourceStats> | undefined;
    return sources && Object.keys(sources).length > 0;
  };

  return (
    <div className="animate-fade-up">
      <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-2">History</p>
      <h1 className="text-2xl font-bold tracking-tighter text-gray-900 mb-8">Run history</h1>

      {runList.length === 0 ? (
        <div className="py-12">
          <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-2">Empty</p>
          <p className="text-gray-600">No runs yet. Start your first search from the dashboard.</p>
          <Link href="/" className="inline-block mt-4 font-mono text-sm text-emerald-600 hover:text-emerald-700 transition-colors">
            Dashboard &rarr;
          </Link>
        </div>
      ) : (
        <div className="divide-y divide-gray-200/60">
          {runList.map((run) => {
            const isOpen = expanded === run.id;
            const sources = run.progress?.sources as Record<string, SourceStats> | undefined;
            const isRunning = run.status === "running" || run.status === "pending";
            const detail = run.progress?.detail as string | undefined;

            return (
              <div key={run.id}>
                <div
                  role={hasSources(run) ? "button" : undefined}
                  tabIndex={hasSources(run) ? 0 : undefined}
                  onClick={() => hasSources(run) && setExpanded(isOpen ? null : run.id)}
                  onKeyDown={(e) => {
                    if (hasSources(run) && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      setExpanded(isOpen ? null : run.id);
                    }
                  }}
                  className={`py-5 grid grid-cols-[2rem_1fr_auto] gap-x-4 items-start ${
                    hasSources(run) ? "cursor-pointer hover:bg-gray-50/80 -mx-3 px-3 rounded-lg transition-colors" : ""
                  }`}
                >
                  {/* Status dot */}
                  <span className={`w-2.5 h-2.5 rounded-full mt-1.5 ${dotColor(run.status)}`} />

                  {/* Main content */}
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 flex items-center gap-2">
                      {formatDate(run.created_at)}
                      {run.trigger === "auto" && (
                        <span className="font-mono text-xs text-gray-400">scheduled</span>
                      )}
                    </p>
                    <p className="font-mono text-xs text-gray-400 mt-1">
                      {isRunning && detail ? detail : statsLine(run.progress || {})}
                    </p>
                    {run.error && (
                      <p className="text-sm text-amber-600 mt-1">
                        {run.error.length > 100 ? `${run.error.slice(0, 100)}…` : run.error}
                      </p>
                    )}
                  </div>

                  {/* Duration + expand hint */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="font-mono text-xs text-gray-400">
                      {isRunning ? "In progress" : formatDuration(run.started_at, run.finished_at)}
                    </span>
                    {hasSources(run) && (
                      <svg
                        className={`w-4 h-4 text-gray-300 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                        fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    )}
                  </div>
                </div>

                {/* Expanded source breakdown */}
                {isOpen && sources && (
                  <div className="pb-4 ml-[2rem] pl-4 animate-fade-up" style={{ animationDuration: "0.2s" }}>
                    <SourceBreakdown sources={sources} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
