"use client";

import { useState } from "react";
import type { JobSummary, JobDetail } from "@/lib/types";
import { jobs as jobsApi } from "@/lib/api";
import { track as analytics } from "@/lib/analytics";

import { SCORE_STRONG, SCORE_VISIBLE } from "@/lib/constants";

function scoreColor(score: number | null): string {
  if (score === null) return "text-gray-400";
  if (score >= SCORE_STRONG) return "text-emerald-600";
  return "text-gray-900";
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
  if (/\$\d+k/i.test(salary)) return salary;
  const s = salary.replace(/\$/g, "").replace(/,/g, "").trim();
  const rangeMatch = s.match(/(\d{4,})\s*[-–]\s*(\d{4,})/);
  if (rangeMatch) {
    const low = Math.round(parseInt(rangeMatch[1]) / 1000);
    const high = Math.round(parseInt(rangeMatch[2]) / 1000);
    return `$${low}k-$${high}k`;
  }
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
  } catch { /* Not JSON */ }
  return flags ? [flags] : [];
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "";
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "1d ago";
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  return weeks === 1 ? "1w ago" : `${weeks}w ago`;
}

interface Props {
  job: JobSummary;
  onStatusChange?: (id: number, status: string) => void;
  availableProviders?: string[];
}

export default function JobCard({ job, onStatusChange, availableProviders = [] }: Props) {
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
  const [compilingPdf, setCompilingPdf] = useState(false);

  const handleExpand = async () => {
    if (expanded) { setExpanded(false); return; }
    if (!detail) {
      setLoading(true);
      try { setDetail(await jobsApi.get(job.id)); }
      finally { setLoading(false); }
    }
    setExpanded(true);
    analytics.jobExpanded(job.id, job.fit_score, job.company);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleExpand();
    }
  };

  const handleStatus = async (status: string) => {
    await jobsApi.updateStatus(job.id, status);
    analytics.jobStatusChanged(job.id, status, job.company);
    onStatusChange?.(job.id, status);
  };

  const salary = formatSalary(job.salary_estimate);
  const track = formatTrack(job.matched_track);
  const sources = job.sources_seen?.join(", ") || "";
  const age = timeAgo(job.posted_at);
  const isRecruiter = job.company_intel?.toLowerCase().includes("recruiter") ||
    job.company_intel?.toLowerCase().includes("job board");



  const isSkipped = job.user_status === "skipped";

  const hasIntel = job.company_intel && !job.company_intel.toLowerCase().includes("no enrichment") && !job.company_intel.toLowerCase().includes("no company intel");

  // Condense company intel for collapsed view: show top 2-3 fields, shorter labels
  const condensedIntel = (() => {
    if (!hasIntel || !job.company_intel) return "";
    return job.company_intel
      .replace(/Stage: /g, "")
      .replace(/Growth: /g, "")
      .replace(/Glassdoor (\d)/g, "GD $1")
      .replace(/ people/g, "")
      .replace(/~(\d+)000/g, "~$1k")
      .replace(/~(\d+)00(?!\d)/g, "~$100");
  })();

  return (
    <div className={`${isSkipped ? "opacity-40" : ""}`}>
      {/* Collapsed row */}
      <div
        role="button"
        tabIndex={0}
        onClick={handleExpand}
        onKeyDown={handleKeyDown}
        className="w-full text-left py-5 grid grid-cols-[3rem_1fr_auto] gap-x-4 items-start hover:bg-gray-100 -mx-3 px-3 rounded-lg transition-colors cursor-pointer group"
      >
        <span className={`font-mono text-lg font-semibold text-right leading-tight ${scoreColor(job.fit_score)}`}>
          {job.fit_score ?? "--"}
        </span>
        <div className="min-w-0">
          {/* Line 1: Title left, salary right */}
          <div className="flex items-baseline justify-between gap-x-4">
            <span className="font-semibold text-gray-900 truncate">{job.title}</span>
            {salary && (
              <span className="font-mono text-sm font-medium text-gray-700 shrink-0">{salary}</span>
            )}
          </div>

          {/* Line 2: Company + location + age left, badges right */}
          <div className="flex items-center justify-between gap-x-3 mt-1">
            <div className="flex flex-wrap items-center gap-x-2 text-sm text-gray-500 min-w-0">
              <span>{job.company}</span>
              {job.location && <><span className="text-gray-300">&middot;</span><span>{job.location}</span></>}
              {age && <><span className="text-gray-300">&middot;</span><span className="text-gray-400 text-xs">{age}</span></>}
            </div>
            <div className="flex items-center gap-x-1.5 shrink-0">
              {isRecruiter && (
                <span className="font-mono text-[10px] uppercase tracking-widest text-amber-600">Recruiter</span>
              )}
              {job.is_new && (
                <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">New</span>
              )}
              {job.user_status === "saved" && (
                <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-600 border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 rounded">Saved</span>
              )}
              {job.user_status === "applied" && (
                <span className="font-mono text-[10px] uppercase tracking-widest text-white bg-emerald-600 px-1.5 py-0.5 rounded">Applied</span>
              )}
              {job.user_status === "skipped" && (
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-400">Skipped</span>
              )}
            </div>
          </div>

          {/* Line 3: Condensed company intel */}
          {condensedIntel && (
            <p className="text-xs text-gray-400 mt-1.5">{condensedIntel}</p>
          )}
        </div>

        {/* Quick actions — visible on hover, hidden if already acted */}
        <div className={`flex items-center gap-1 shrink-0 self-center transition-opacity ${!job.user_status ? "opacity-0 group-hover:opacity-100" : "opacity-0 pointer-events-none"}`}>
            <button
              onClick={(e) => { e.stopPropagation(); handleStatus("saved"); }}
              title="Save"
              className="w-7 h-7 rounded-full hover:bg-gray-200 flex items-center justify-center text-gray-400 hover:text-emerald-600 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleStatus("skipped"); }}
              title="Skip"
              className="w-7 h-7 rounded-full hover:bg-gray-200 flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="animate-fade-up" style={{ animationDuration: "0.2s" }}>
          <div className="ml-[calc(3rem+1rem)] pb-6 space-y-6">
            {loading ? (
              <div className="space-y-3">
                <div className="h-3 w-3/4 rounded bg-gray-200 animate-pulse" />
                <div className="h-3 w-1/2 rounded bg-gray-200 animate-pulse" />
              </div>
            ) : detail ? (
              <div className="space-y-6">

                {/* Compact action bar — first thing visible */}
                <div className="flex flex-wrap items-center gap-2">
                  {job.url && (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="rounded-full bg-gray-900 px-4 py-1.5 text-xs font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0"
                    >
                      View listing
                    </a>
                  )}
                  {detail?.career_page_url && detail.career_page_url !== job.url && (
                    <a
                      href={detail.career_page_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0"
                    >
                      Apply direct
                    </a>
                  )}
                  <span className="w-px h-4 bg-gray-200 mx-1" />
                  {(["saved", "applied", "skipped"] as const).map((s) => (
                    <button
                      key={s}
                      onClick={(e) => { e.stopPropagation(); handleStatus(s); }}
                      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                        job.user_status === s
                          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                          : "border-gray-300 text-gray-600 hover:bg-white"
                      }`}
                    >
                      {s === "saved" ? "Save" : s === "applied" ? "Applied" : "Skip"}
                    </button>
                  ))}
                  {sources && (
                    <span className="ml-auto font-mono text-[11px] text-gray-400">via {sources}</span>
                  )}
                </div>

                {/* Interest note — the star, biggest text, most prominent */}
                {detail.interest_note && (
                  <div className="border-l-2 border-emerald-600 pl-4">
                    <p className="text-base text-gray-900 leading-relaxed max-w-[60ch]">{detail.interest_note}</p>
                  </div>
                )}

                {/* Score reasoning — secondary prose */}
                {detail.score_reasoning && (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wider text-gray-400 mb-2">Why this score</p>
                    <p className="text-sm text-gray-600 leading-relaxed max-w-[65ch]">{detail.score_reasoning}</p>
                  </div>
                )}

                {/* Yellow flags — warning treatment */}
                {formatYellowFlags(detail.yellow_flags).length > 0 && (
                  <div className="rounded-lg bg-amber-50 border border-amber-200/60 px-4 py-3">
                    <p className="text-xs font-medium uppercase tracking-wider text-amber-600 mb-1.5">Watch out for</p>
                    <div className="space-y-1">
                      {formatYellowFlags(detail.yellow_flags).map((flag, i) => (
                        <p key={i} className="text-sm text-amber-800">{flag}</p>
                      ))}
                    </div>
                  </div>
                )}

                {/* Company intel — compact data grid */}
                {detail.enrichment && (() => {
                  const e = detail.enrichment as Record<string, string | number | string[] | null>;
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
                    <div className="rounded-lg bg-gray-100/60 px-4 py-3">
                      <p className="text-xs font-medium uppercase tracking-wider text-gray-400 mb-2">Company</p>
                      {hasDescription && (
                        <p className="text-sm text-gray-700 mb-3 max-w-[65ch]">{String(e.domain_description)}</p>
                      )}
                      <div className="space-y-2 text-sm">
                        {hasStage && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Stage</span>
                            <span className="text-gray-700">{String(e.stage)}</span>
                          </div>
                        )}
                        {hasHeadcount && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Team size</span>
                            <span className="text-gray-700">~{String(e.headcount_estimate)} people</span>
                          </div>
                        )}
                        {hasGlassdoor && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Glassdoor</span>
                            <span className="text-gray-700">{String(e.glassdoor_rating)} / 5.0</span>
                          </div>
                        )}
                        {hasGrowth && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Growth</span>
                            <span className="text-gray-700">{String(e.growth_signal)}</span>
                          </div>
                        )}
                        {hasOss && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Open source</span>
                            <span className="text-gray-700">{String(e.oss_presence)}</span>
                          </div>
                        )}
                        {hasTech && (
                          <div className="flex items-baseline gap-2">
                            <span className="text-gray-400 font-mono text-xs w-20 shrink-0">Tech stack</span>
                            <span className="text-gray-700">{(e.tech_stack as string[]).join(", ")}</span>
                          </div>
                        )}
                      </div>
                      <p className="mt-3 font-mono text-[10px] text-gray-400">AI-researched from public sources. Verify before relying on these numbers.</p>
                    </div>
                  );
                })()}

                {/* Tools: Resume + Cover letter */}
                <div className="pt-4 border-t border-gray-200/60 space-y-4">
                  <p className="text-xs font-medium uppercase tracking-wider text-gray-400">Tools</p>
                  {!job.has_tailored_resume && !tailoring && (
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        setTailoring(true);
                        setTailorError("");
                        try {
                          const result = await jobsApi.tailor(job.id);
                          setTailorResult(result);
                          analytics.resumeTailored(job.id, job.company);
                          onStatusChange?.(job.id, "");
                        } catch (err) {
                          const msg = err instanceof Error ? err.message : "Tailoring failed";
                          setTailorError(msg);
                          analytics.resumeTailorFailed(job.id, job.company, msg);
                        } finally {
                          setTailoring(false);
                        }
                      }}
                      className="rounded-full border border-gray-300 px-4 py-1.5 text-xs font-medium text-gray-600 hover:bg-white transition-colors"
                    >
                      Tailor resume
                    </button>
                  )}
                  {tailoring && (
                    <p className="text-sm text-gray-500 font-mono text-xs">Tailoring resume (~15s)...</p>
                  )}
                  {tailorError && <p className="text-sm text-red-600">{tailorError}</p>}
                  {(job.has_tailored_resume || tailorResult) && (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={async (e) => {
                            e.stopPropagation();
                            try {
                              await jobsApi.downloadResume(job.id, "tex");
                              analytics.resumeDownloaded(job.id, job.company);
                            } catch { setTailorError("Download failed"); }
                          }}
                          className="rounded-full border border-gray-300 px-4 py-1.5 text-xs font-medium text-gray-600 hover:bg-white transition-colors"
                        >
                          Download .tex
                        </button>
                        <button
                          disabled={compilingPdf}
                          onClick={async (e) => {
                            e.stopPropagation();
                            setCompilingPdf(true);
                            setTailorError("");
                            try {
                              await jobsApi.downloadResume(job.id, "pdf");
                              analytics.resumeDownloaded(job.id, job.company);
                            } catch (err) {
                              const msg = err instanceof Error ? err.message : "PDF compilation failed";
                              setTailorError(msg);
                            } finally { setCompilingPdf(false); }
                          }}
                          className={`rounded-full border px-4 py-1.5 text-xs font-medium transition-colors ${
                            compilingPdf
                              ? "border-gray-200 text-gray-400 cursor-wait"
                              : "border-gray-300 text-gray-600 hover:bg-white"
                          }`}
                        >
                          {compilingPdf ? "Compiling..." : "Download PDF"}
                        </button>
                      </div>
                      <p className="text-xs text-amber-700 leading-relaxed max-w-[65ch]">
                        Review before sending. This resume was adjusted by AI to better match this role.
                        It only uses facts from your original, but always verify the final version.
                      </p>
                    </div>
                  )}
                  {tailorResult?.changes_made && tailorResult.changes_made.length > 0 && (
                    <ul className="text-xs text-gray-500 space-y-0.5 font-mono">
                      {tailorResult.changes_made.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  )}

                  {!generatingLetter && (() => {
                    const models: { value: string; label: string; provider: string }[] = [
                      { value: "gemini-2.0-flash", label: "Gemini 2.0 Flash", provider: "gemini" },
                      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash", provider: "gemini" },
                      { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro", provider: "gemini" },
                      { value: "gpt-4o", label: "GPT-4o", provider: "openai" },
                      { value: "gpt-4o-mini", label: "GPT-4o Mini", provider: "openai" },
                      { value: "claude-sonnet-4-20250514", label: "Claude Sonnet 4", provider: "anthropic" },
                      { value: "claude-3-5-haiku-latest", label: "Claude 3.5 Haiku", provider: "anthropic" },
                    ];
                    const usable = models.filter((m) => availableProviders.includes(m.provider));
                    const hasKey = availableProviders.length > 0;

                    return (
                      <div className="flex flex-col sm:flex-row sm:items-center gap-2 flex-wrap">
                        <button
                          disabled={!hasKey}
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
                              analytics.coverLetterGenerated(job.id, result.model_used, job.company, !!(detail?.cover_letter || coverLetter));
                            } catch (err) {
                              const msg = err instanceof Error ? err.message : "Generation failed";
                              setLetterError(msg);
                              analytics.coverLetterFailed(job.id, job.company, msg);
                            } finally { setGeneratingLetter(false); }
                          }}
                          className={`rounded-full border px-4 py-1.5 text-xs font-medium transition-colors ${
                            hasKey
                              ? "border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                              : "border-gray-200 text-gray-400 cursor-not-allowed"
                          }`}
                        >
                          {(detail?.cover_letter || coverLetter) ? "Regenerate" : "Generate"} cover letter
                        </button>
                        {hasKey && (
                          <select
                            value={clModel}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => { e.stopPropagation(); setClModel(e.target.value); if (e.target.value) analytics.coverLetterModelChanged(e.target.value); }}
                            className="rounded-full border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-600"
                          >
                            <option value="">Default model</option>
                            {(["gemini", "openai", "anthropic"] as const)
                              .filter((p) => availableProviders.includes(p))
                              .map((p) => (
                                <optgroup key={p} label={p === "gemini" ? "Gemini" : p === "openai" ? "OpenAI" : "Anthropic"}>
                                  {usable.filter((m) => m.provider === p).map((m) => (
                                    <option key={m.value} value={m.value}>{m.label}</option>
                                  ))}
                                </optgroup>
                              ))}
                          </select>
                        )}
                        {!hasKey && (
                          <a href="/profile" className="text-xs text-emerald-600 hover:text-emerald-700">
                            Add an API key to enable
                          </a>
                        )}
                      </div>
                    );
                  })()}
                  {generatingLetter && (
                    <p className="text-xs text-gray-500 font-mono">Writing cover letter (~10s)...</p>
                  )}
                  {letterError && <p className="text-sm text-red-600">{letterError}</p>}
                  {(detail?.cover_letter || coverLetter) && (() => {
                    const text = coverLetter || detail?.cover_letter || "";
                    return (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <p className="font-mono text-[10px] uppercase tracking-widest text-gray-400">
                            Cover letter
                          </p>
                          <div className="flex items-center gap-2">
                            {letterModel && (
                              <span className="font-mono text-xs text-gray-400">via {letterModel}</span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard.writeText(text);
                                setCopied(true);
                                analytics.coverLetterCopied(job.id, job.company);
                                setTimeout(() => setCopied(false), 2000);
                              }}
                              className="rounded-full border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-white transition-colors"
                            >
                              {copied ? "Copied" : "Copy"}
                            </button>
                          </div>
                        </div>
                        <div className="rounded-lg bg-white border border-gray-200/60 p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                          {text}
                        </div>
                        <p className="text-xs text-amber-700 leading-relaxed max-w-[65ch]">
                          Review before sending. AI can get details wrong or miss nuance.
                          Read carefully, add your personal touch, and verify any claims about the company.
                        </p>
                      </div>
                    );
                  })()}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
