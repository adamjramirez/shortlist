"use client";

import { useState } from "react";
import type { JobSummary, JobDetail } from "@/lib/types";
import { jobs as jobsApi } from "@/lib/api";

import { SCORE_STRONG, SCORE_VISIBLE } from "@/lib/constants";

function scoreColor(score: number | null): string {
  if (score === null) return "bg-gray-100 text-gray-600";
  if (score >= SCORE_STRONG) return "bg-green-100 text-green-800";
  if (score >= SCORE_VISIBLE) return "bg-yellow-100 text-yellow-800";
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
  // Already formatted like $200k-$300k
  if (/\$\d+k/i.test(salary)) return salary;
  // Clean up common LLM output formats
  const s = salary.replace(/\$/g, "").replace(/,/g, "").trim();
  // Handle range like "220000-350000"
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
  return salary.length > 30 ? "" : salary;
}

function formatYellowFlags(flags: string | null): string[] {
  if (!flags) return [];
  try {
    const parsed = JSON.parse(flags);
    if (Array.isArray(parsed)) return parsed.filter(Boolean);
  } catch {
    // Not JSON
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
  const sources = job.sources_seen?.join(", ") || "";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 hover:border-gray-300 transition-colors">
      <div
        className="flex cursor-pointer items-start justify-between"
        onClick={handleExpand}
      >
        <div className="flex-1 min-w-0">
          {/* Row 1: Score + Title */}
          <div className="flex items-center gap-3">
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-sm font-bold ${scoreColor(job.fit_score)}`}
            >
              {job.fit_score ?? "—"}
            </span>
            <h3 className="font-semibold text-gray-900 truncate">{job.title}</h3>
          </div>

          {/* Row 2: Company · Location · Salary */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
            <span className="font-medium text-gray-700">{job.company}</span>
            {job.location && (
              <>
                <span className="text-gray-300">·</span>
                <span className="text-gray-500">📍 {job.location}</span>
              </>
            )}
            {salary && (
              <>
                <span className="text-gray-300">·</span>
                <span className="text-gray-600 font-medium">{salary}</span>
              </>
            )}
          </div>

          {/* Row 3: Track + Company intel + Sources */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            {track && (
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-600 font-medium">
                {track}
              </span>
            )}
            {job.company_intel && (
              <span className="text-gray-400">{job.company_intel}</span>
            )}
            {sources && (
              <span className="text-gray-300">via {sources}</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 ml-2 shrink-0">
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
              {detail.score_reasoning && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400 mb-1">
                    Why this score
                  </p>
                  <p className="text-sm text-gray-700 leading-relaxed">
                    {detail.score_reasoning}
                  </p>
                </div>
              )}

              {formatYellowFlags(detail.yellow_flags).length > 0 && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400 mb-1">
                    ⚠️ Watch out for
                  </p>
                  <ul className="space-y-0.5">
                    {formatYellowFlags(detail.yellow_flags).map((flag, i) => (
                      <li key={i} className="text-sm text-yellow-700">
                        • {flag}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.enrichment && (() => {
                const e = detail.enrichment as Record<string, string | number | string[] | null>;
                return (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400 mb-1">
                    Company Intel
                  </p>
                  <div className="text-sm text-gray-600 space-y-1">
                    {e.domain_description && (
                      <p className="italic">{String(e.domain_description)}</p>
                    )}
                    <div className="flex flex-wrap gap-2 text-xs">
                      {e.stage && e.stage !== "unknown" && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">{String(e.stage)}</span>
                      )}
                      {e.headcount_estimate && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">~{String(e.headcount_estimate)} people</span>
                      )}
                      {e.glassdoor_rating && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">⭐ {String(e.glassdoor_rating)}</span>
                      )}
                      {e.growth_signal && e.growth_signal !== "unknown" && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">{String(e.growth_signal)}</span>
                      )}
                      {e.oss_presence && !["unknown", "weak"].includes(String(e.oss_presence)) && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">OSS: {String(e.oss_presence)}</span>
                      )}
                      {Array.isArray(e.tech_stack) && e.tech_stack.length > 0 && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">{(e.tech_stack as string[]).join(", ")}</span>
                      )}
                    </div>
                  </div>
                </div>
                );
              })()}

              <div className="flex flex-wrap items-center gap-2 pt-2">
                {job.url && (
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    View Listing →
                  </a>
                )}
                {(["saved", "applied", "skipped"] as const).map((s) => (
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
                    {s === "saved" ? "⭐ Save" : s === "applied" ? "✅ Applied" : "Skip"}
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
