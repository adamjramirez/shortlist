"use client";

import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/use-require-auth";
import { runs as runsApi } from "@/lib/api";
import type { Run } from "@/lib/types";

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    completed: "bg-green-100 text-green-800",
    running: "bg-blue-100 text-blue-800",
    pending: "bg-yellow-100 text-yellow-800",
    failed: "bg-red-100 text-red-800",
  };
  return colors[status] ?? "bg-gray-100 text-gray-600";
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
    return <p className="mt-10 text-center text-gray-400">Loading...</p>;
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold">Run History</h1>
      {runList.length === 0 ? (
        <p className="text-gray-500">No runs yet.</p>
      ) : (
        <div className="space-y-3">
          {runList.map((run) => (
            <div
              key={run.id}
              className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${statusBadge(run.status)}`}
                >
                  {run.status}
                </span>
                <span className="text-sm text-gray-600">
                  {formatDate(run.created_at)}
                </span>
              </div>
              <div className="text-sm text-gray-500">
                {run.finished_at && (
                  <span>
                    Finished {formatDate(run.finished_at)}
                  </span>
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
