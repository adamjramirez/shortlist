"use client";

import { useState } from "react";
import type { JobSummary, JobDetail } from "@/lib/types";
import { jobs as jobsApi } from "@/lib/api";

function scoreColor(score: number | null): string {
  if (score === null) return "bg-gray-100 text-gray-600";
  if (score >= 80) return "bg-green-100 text-green-800";
  if (score >= 60) return "bg-yellow-100 text-yellow-800";
  return "bg-red-100 text-red-800";
}

function formatTrack(track: string | null): string {
  if (!track) return "";
  return track
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bVp\b/g, "VP")
    .replace(/\bEm\b/g, "EM")
    .replace(/\bAi\b/g, "AI");
}

function formatSalary(salary: string | null): string {
  if (!salary) return "";
  // Clean up common LLM output formats
  let s = salary.replace(/\$/g, "").replace(/,/g, "").trim();
  // Handle range like "220000-350000" or "220000 - 350000"
  const rangeMatch = s.match(/(\d{4,})\s*[-–]\s*(\d{4,})/);
  if (rangeMatch) {
    const low = Math.round(parseInt(rangeMatch[1]) / 1000);
    const high = Math.round(parseInt(rangeMatch[2]) / 1000);
    return `$${low}k–$${high}k`;
  }
  // Single number
  const singleMatch = s.match(/(\d{4,})/);
  if (singleMatch) {
    const val = Math.round(parseInt(singleMatch[1]) / 1000);
    return `$${val}k`;
  }
  // If it's already formatted or weird, truncate
  return salary.length > 30 ? "" : salary;
}

function formatYellowFlags(flags: string | null): string[] {
  if (!flags) return [];
  try {
    const parsed = JSON.parse(flags);
    if (Array.isArray(parsed)) return parsed.filter(Boolean);
  } catch {
    // Not JSON, treat as plain text
  }
  return flags ? [flags] : [];
}

interface Props {
  job: JobSummary;
  onStatusChange?: (id: number, status: string) => void;
}

export default function JobCard({ job, onStatusChange }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const handleExpand = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (!detail) {
      setLoading(true);
      try {
        setDetail(await jobsApi.get(job.id));
      } finally {
        setLoading(false);
      }
    }
    setExpanded(true);
  };

  const handleStatus = async (status: string) => {
    await jobsApi.updateStatus(job.id, status);
    onStatusChange?.(job.id, status);
  };

  const salary = formatSalary(job.salary_estimate);
  const track = formatTrack(job.matched_track);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div
        className="flex cursor-pointer items-start justify-between"
        onClick={handleExpand}
      >
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-sm font-semibold ${scoreColor(job.fit_score)}`}
            >
              {job.fit_score ?? "—"}
            </span>
            <h3 className="font-medium text-gray-900">{job.title}</h3>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
            <span className="font-medium text-gray-700">{job.company}</span>
            {salary && (
              <>
                <span className="text-gray-300">·</span>
                <span>{salary}</span>
              </>
            )}
            {track && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                {track}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {job.user_status && (
            <span className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
              {job.user_status}
            </span>
          )}
          <span className="text-gray-400">{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          {loading ? (
            <p className="text-sm text-gray-400">Loading...</p>
          ) : detail ? (
            <div className="space-y-3">
              {detail.location && (
                <div className="text-sm text-gray-500">
                  📍 {detail.location}
                </div>
              )}
              {detail.score_reasoning && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400">
                    Why this score
                  </p>
                  <p className="text-sm text-gray-700">
                    {detail.score_reasoning}
                  </p>
                </div>
              )}
              {formatYellowFlags(detail.yellow_flags).length > 0 && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400">
                    ⚠️ Watch out for
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {formatYellowFlags(detail.yellow_flags).map((flag, i) => (
                      <li key={i} className="text-sm text-yellow-700">
                        • {flag}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {detail.enrichment && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400">
                    Company Intel
                  </p>
                  <pre className="text-xs text-gray-600 whitespace-pre-wrap">
                    {JSON.stringify(detail.enrichment, null, 2)}
                  </pre>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 pt-2">
                {job.url && (
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
                  >
                    Apply →
                  </a>
                )}
                {(["applied", "skipped", "saved"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleStatus(s);
                    }}
                    className={`rounded border px-3 py-1.5 text-sm ${
                      job.user_status === s
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-300 text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
