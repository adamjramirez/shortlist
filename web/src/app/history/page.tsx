"use client";

import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/use-require-auth";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";
import { HistorySkeleton } from "@/components/Skeleton";

function statusColor(status: string): string {
  switch (status) {
    case "completed": return "text-emerald-600";
    case "running":
    case "pending": return "text-gray-500";
    case "failed": return "text-red-500";
    default: return "text-gray-400";
  }
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function HistoryPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [runList, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading || !user) return;
    runsApi
      .list()
      .then(setRuns)
      .finally(() => setLoading(false));
  }, [user, authLoading]);

  if (loading) {
    return <HistorySkeleton />;
  }

  return (
    <div className="animate-fade-up">
      <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-2">History</p>
      <h1 className="text-2xl font-bold tracking-tighter text-gray-900 mb-8">Run history</h1>
      {runList.length === 0 ? (
        <div className="py-12 text-center">
          <p className="text-gray-600">No runs yet.</p>
          <p className="text-sm text-gray-400 mt-1">Go to the dashboard and click Run to start your first search.</p>
        </div>
      ) : (
        <div className="divide-y divide-gray-200/60">
          {runList.map((run) => (
            <div
              key={run.id}
              className="py-4 grid grid-cols-[5rem_1fr_auto] gap-x-4 items-baseline"
            >
              <span className={`font-mono text-sm font-medium ${statusColor(run.status)}`}>
                {run.status}
              </span>
              <span className="text-sm text-gray-600">
                {formatDate(run.created_at)}
              </span>
              <div className="text-sm text-gray-400 font-mono text-xs">
                {run.finished_at && (
                  <span>{formatDate(run.finished_at)}</span>
                )}
                {run.error && (
                  <span className="text-red-500">{run.error}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
