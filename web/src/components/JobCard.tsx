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
  const [tailoring, setTailoring] = useState(false);
  const [tailorResult, setTailorResult] = useState<{ changes_made: string[] } | null>(null);
  const [tailorError, setTailorError] = useState("");
  const [generatingLetter, setGeneratingLetter] = useState(false);
  const [coverLetter, setCoverLetter] = useState<string | null>(null);
  const [letterModel, setLetterModel] = useState("");
  const [letterError, setLetterError] = useState("");
  const [copied, setCopied] = useState(false);
  const [clModel, setClModel] = useState("");

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
            {job.is_new && (
              <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-700 text-xs font-medium">
                New
              </span>
            )}
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

              {detail.interest_note && (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400 mb-1">
                    Why you might be interested
                  </p>
                  <p className="text-sm text-gray-600 italic leading-relaxed">
                    {detail.interest_note}
                  </p>
                </div>
              )}

              {detail.enrichment && (() => {
                const e = detail.enrichment as Record<string, string | number | string[] | null>;
                // Check if there's anything meaningful to show
                const hasStage = e.stage && e.stage !== "unknown";
                const hasHeadcount = !!e.headcount_estimate;
                const hasGlassdoor = !!e.glassdoor_rating;
                const hasGrowth = e.growth_signal && e.growth_signal !== "unknown";
                const hasOss = e.oss_presence && !["unknown", "weak"].includes(String(e.oss_presence));
                const hasTech = Array.isArray(e.tech_stack) && e.tech_stack.length > 0;
                const hasDescription = !!e.domain_description;
                const hasAnything = hasStage || hasHeadcount || hasGlassdoor || hasGrowth || hasOss || hasTech || hasDescription;
                if (!hasAnything) return null;
                return (
                <div>
                  <p className="text-xs font-medium uppercase text-gray-400 mb-1">
                    Company Intel
                  </p>
                  <div className="text-sm text-gray-600 space-y-1">
                    {hasDescription && (
                      <p className="italic">{String(e.domain_description)}</p>
                    )}
                    <div className="flex flex-wrap gap-2 text-xs">
                      {hasStage && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">{String(e.stage)}</span>
                      )}
                      {hasHeadcount && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">~{String(e.headcount_estimate)} people</span>
                      )}
                      {hasGlassdoor && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">⭐ {String(e.glassdoor_rating)}</span>
                      )}
                      {hasGrowth && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">{String(e.growth_signal)}</span>
                      )}
                      {hasOss && (
                        <span className="rounded bg-gray-100 px-2 py-0.5">OSS: {String(e.oss_presence)}</span>
                      )}
                      {hasTech && (
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
                {detail?.career_page_url && detail.career_page_url !== job.url && (
                  <a
                    href={detail.career_page_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100"
                  >
                    Apply Direct →
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

              {/* Resume tailoring */}
              <div className="pt-2 border-t border-gray-100">
                {!job.has_tailored_resume && !tailoring && (
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      setTailoring(true);
                      setTailorError("");
                      try {
                        const result = await jobsApi.tailor(job.id);
                        setTailorResult(result);
                        onStatusChange?.(job.id, "");
                      } catch (err) {
                        setTailorError(err instanceof Error ? err.message : "Tailoring failed");
                      } finally {
                        setTailoring(false);
                      }
                    }}
                    className="rounded border border-purple-300 bg-purple-50 px-3 py-1.5 text-sm font-medium text-purple-700 hover:bg-purple-100"
                  >
                    ✨ Generate Tailored Resume
                  </button>
                )}
                {tailoring && (
                  <p className="text-sm text-gray-500 animate-pulse">
                    ⏳ Tailoring resume (~15s)…
                  </p>
                )}
                {tailorError && (
                  <p className="text-sm text-red-600">{tailorError}</p>
                )}
                {(job.has_tailored_resume || tailorResult) && (
                  <div className="space-y-2">
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        try {
                          await jobsApi.downloadResume(job.id);
                        } catch {
                          setTailorError("Download failed");
                        }
                      }}
                      className="inline-flex items-center rounded border border-purple-300 bg-purple-50 px-3 py-1.5 text-sm font-medium text-purple-700 hover:bg-purple-100"
                    >
                      📄 Download Tailored Resume (.tex)
                    </button>
                    <p className="text-xs text-gray-400">
                      This downloads a LaTeX (.tex) file. To convert to PDF, paste it into{" "}
                      <a href="https://www.overleaf.com" target="_blank" rel="noopener noreferrer"
                         className="underline hover:text-gray-600">Overleaf</a>
                      {" "}or ask ChatGPT / Claude to compile it for you.
                    </p>
                  </div>
                )}
                {tailorResult?.changes_made && tailorResult.changes_made.length > 0 && (
                  <ul className="mt-1 text-xs text-gray-500 space-y-0.5">
                    {tailorResult.changes_made.map((c, i) => (
                      <li key={i}>• {c}</li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Cover letter */}
              <div className="pt-2 border-t border-gray-100 space-y-2">
                {!generatingLetter && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        setGeneratingLetter(true);
                        setLetterError("");
                        try {
                          const result = await jobsApi.generateCoverLetter(
                            job.id,
                            clModel || undefined,
                            !!(detail?.cover_letter || coverLetter),
                          );
                          setCoverLetter(result.cover_letter);
                          setLetterModel(result.model_used);
                        } catch (err) {
                          setLetterError(err instanceof Error ? err.message : "Generation failed");
                        } finally {
                          setGeneratingLetter(false);
                        }
                      }}
                      className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
                    >
                      {(detail?.cover_letter || coverLetter) ? "🔄 Regenerate" : "✍️ Generate"} Cover Letter
                    </button>
                    <select
                      value={clModel}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => { e.stopPropagation(); setClModel(e.target.value); }}
                      className="rounded border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-600"
                    >
                      <option value="">Default model</option>
                      <optgroup label="Gemini">
                        <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                        <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                        <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                      </optgroup>
                      <optgroup label="OpenAI">
                        <option value="gpt-4o">GPT-4o</option>
                        <option value="gpt-4o-mini">GPT-4o Mini</option>
                      </optgroup>
                      <optgroup label="Anthropic">
                        <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
                        <option value="claude-3-5-haiku-latest">Claude 3.5 Haiku</option>
                      </optgroup>
                    </select>
                  </div>
                )}
                {generatingLetter && (
                  <p className="text-sm text-gray-500 animate-pulse">
                    ✍️ Writing cover letter (~10s)…
                  </p>
                )}
                {letterError && (
                  <p className="text-sm text-red-600">{letterError}</p>
                )}
                {(detail?.cover_letter || coverLetter) && (() => {
                  const text = coverLetter || detail?.cover_letter || "";
                  return (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-medium uppercase text-gray-400">
                          Cover Letter
                        </p>
                        <div className="flex items-center gap-2">
                          {letterModel && (
                            <span className="text-xs text-gray-400">
                              via {letterModel}
                            </span>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              navigator.clipboard.writeText(text);
                              setCopied(true);
                              setTimeout(() => setCopied(false), 2000);
                            }}
                            className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-50"
                          >
                            {copied ? "✓ Copied!" : "📋 Copy"}
                          </button>
                        </div>
                      </div>
                      <div className="rounded-lg bg-gray-50 p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                        {text}
                      </div>
                      <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800 space-y-1">
                        <p className="font-medium">⚠️ Review before sending</p>
                        <p>
                          This is a strong starting point, not a finished letter. AI can get details wrong
                          or miss nuance. Read it carefully, add your personal touch, and verify any claims
                          about the company. The best cover letters have a human voice.
                        </p>
                        <p className="text-amber-600">
                          💡 Want a different tone? Change your model in{" "}
                          <a href="/profile" className="underline hover:text-amber-700">Profile settings</a>
                          {" "}— different models write differently.
                        </p>
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
