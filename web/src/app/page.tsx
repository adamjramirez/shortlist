"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { track as analytics } from "@/lib/analytics";
import { profile as profileApi, resumes as resumesApi, jobs as jobsApi } from "@/lib/api";
import type { Profile, Resume, JobSummary, JobStatusCounts } from "@/lib/types";
import OnboardingChecklist from "@/components/OnboardingChecklist";
import JobCard from "@/components/JobCard";
import RunButton from "@/components/RunButton";
import { SCORE_VISIBLE, SCORE_STRONG } from "@/lib/constants";
import { DashboardSkeleton } from "@/components/Skeleton";

const DEMO_JOBS = [
  {
    score: 92,
    title: "VP Engineering, Infrastructure",
    company: "Vercel",
    location: "Remote (US)",
    salary: "$320k -- $400k",
    reasoning: "Strong fit. Remote, Series D, 200+ eng. Matches AI-native platform focus and leadership scope.",
    intel: {
      stage: "Series D -- $250M raised",
      headcount: "~230 engineers",
      culture: "Async-first, high autonomy, ships fast. Strong OSS DNA from Next.js heritage.",
      recent: "Launched v0 (AI), acquired Turborepo. Revenue growing 3x YoY.",
    },
    interest: "This is the role. Infrastructure VP at the company defining how the web deploys. You'd own the platform hundreds of thousands of devs ship on daily. The scope is exactly what you've been building toward -- and they're remote-first, not remote-tolerant.",
  },
  {
    score: 87,
    title: "Engineering Manager, Payments Core",
    company: "Stripe",
    location: "San Francisco (Hybrid 3 days)",
    salary: "$280k -- $350k + equity",
    reasoning: "Scope aligns with leadership track. 40-person org, elite eng culture. Hybrid is the tradeoff.",
    intel: {
      stage: "Late stage -- $95B valuation",
      headcount: "~2,000 engineers",
      culture: "Writing culture (memos over meetings), high bar, intense but collegial. Promotes from within.",
      recent: "Launched Stripe Billing v2, expanded to crypto on-ramps. IPO rumors persist.",
    },
    interest: "Payments Core is the beating heart of Stripe -- the money movement layer everything else depends on. You'd manage ~12 ICs doing genuinely hard distributed systems work. The hybrid requirement is real (SF 3 days) but the caliber of the team and the problems offset it. Worth a conversation.",
  },
  {
    score: 78,
    title: "Head of Engineering",
    company: "Linear",
    location: "Remote (US/EU)",
    salary: "$250k -- $300k + equity",
    reasoning: "Right level but small team (18 eng). Salary range below target. Exceptional product.",
    intel: {
      stage: "Series B -- $52M raised",
      headcount: "~18 engineers, 35 total",
      culture: "Craft-obsessed. Small team, no middle management. Everyone ships. Design-driven.",
      recent: "Launched Linear Asks, Initiatives. Growing fast in enterprise segment.",
    },
    interest: "The product is beautiful and the team is exceptional, but this is a different kind of role -- you'd be player-coach in a team of 18, not leading a scaled org. The salary ceiling is $50k below your minimum. If you'd take a comp hit for the chance to shape a generational product company early, it's interesting. Otherwise, pass.",
  },
  {
    score: 76,
    title: "Director of Platform Engineering",
    company: "Notion",
    location: "San Francisco (Hybrid 2 days)",
    salary: "$290k -- $360k + equity",
    reasoning: "Good scope and comp. Hybrid is lighter than most. Platform team is growing fast.",
    intel: {
      stage: "Series C -- $340M raised -- $10B valuation",
      headcount: "~120 engineers",
      culture: "Mission-driven, collaborative. Known for thoughtful product decisions. Work-life balance better than most.",
      recent: "Launched Notion AI, Projects, and Calendar. Enterprise revenue doubled.",
    },
    interest: "Platform engineering at Notion means the infrastructure under the collaborative editor used by millions. It's a meaty technical challenge with real scale. The 2-day hybrid is light, and SF comp is strong. Not as exciting as Vercel's scope but a solid top-3 pick.",
  },
];

function DemoResults() {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div className="mx-auto max-w-[900px]">
      {/* Pipeline stats */}
      <div className="flex items-center gap-6 mb-5 font-mono text-xs text-gray-500 animate-fade-up" style={{ animationDelay: "0.25s" }}>
        <span>127 collected</span>
        <span className="text-gray-300">&rarr;</span>
        <span>43 passed filters</span>
        <span className="text-gray-300">&rarr;</span>
        <span className="text-emerald-600 font-semibold">4 matches</span>
      </div>

      <div className="space-y-1">
        {DEMO_JOBS.map((job, i) => {
          const isOpen = expanded === i;
          const scoreColor = job.score >= 85
            ? "text-emerald-600"
            : "text-gray-900";

          return (
            <div key={i} className="border-b border-gray-200/60 animate-fade-up" style={{ animationDelay: `${0.3 + i * 0.08}s` }}>
              <button
                onClick={() => setExpanded(isOpen ? null : i)}
                className="w-full text-left py-5 grid grid-cols-[3rem_1fr_1rem] gap-x-4 items-start hover:bg-gray-50/80 -mx-3 px-3 rounded-lg transition-colors cursor-pointer"
              >
                <span className={`font-mono text-lg font-semibold text-right leading-tight ${scoreColor}`}>
                  {job.score}
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold text-gray-900">{job.title}</span>
                    <span className="text-sm text-gray-500">{job.company}</span>
                  </div>
                  <div className="flex flex-wrap gap-x-3 mt-1 font-mono text-xs text-gray-400">
                    <span>{job.location}</span>
                    <span>{job.salary}</span>
                  </div>
                  <p className="text-gray-600 text-sm mt-1.5 line-clamp-1 leading-relaxed">{job.reasoning}</p>
                </div>
                <svg
                  className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                  fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {isOpen && (
                <div className="pb-6 animate-fade-up" style={{ animationDuration: "0.2s" }}>
                  <div className="ml-[calc(3rem+1rem)] mr-[calc(1rem+1rem)] space-y-6">

                    {/* Interest note — the star */}
                    <div className="border-l-2 border-emerald-600 pl-4">
                      <p className="text-base text-gray-900 leading-relaxed max-w-[60ch]">{job.interest}</p>
                    </div>

                    {/* Score reasoning */}
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wider text-gray-400 mb-2">Why this score</p>
                      <p className="text-sm text-gray-600 leading-relaxed max-w-[65ch]">{job.reasoning}</p>
                    </div>

                    {/* Company intel — data grid */}
                    <div className="rounded-lg bg-gray-100/60 px-4 py-3">
                      <p className="text-xs font-medium uppercase tracking-wider text-gray-400 mb-2">Company</p>
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-xs">
                        <div><span className="text-gray-400">Stage </span><span className="text-gray-700">{job.intel.stage}</span></div>
                        <div><span className="text-gray-400">Team </span><span className="text-gray-700">{job.intel.headcount}</span></div>
                        <div className="col-span-2"><span className="text-gray-400">Culture </span><span className="text-gray-700">{job.intel.culture}</span></div>
                        <div className="col-span-2"><span className="text-gray-400">Recent </span><span className="text-gray-700">{job.intel.recent}</span></div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3">
                      <span className="rounded-full bg-gray-900 px-4 py-1.5 text-xs font-medium text-white">
                        Tailor resume
                      </span>
                      <span className="rounded-full border border-gray-300 px-4 py-1.5 text-xs font-medium text-gray-600">
                        View posting
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Bottom */}
      <div className="mt-8 pt-6 border-t border-gray-200/60 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <p className="text-sm text-gray-500">
          Gemini API key (free) + your resume. That&apos;s it.
        </p>
        <Link href="/getting-started" className="font-mono text-sm text-emerald-600 hover:text-emerald-700 transition-colors">
          Setup guide &rarr;
        </Link>
      </div>
    </div>
  );
}

function Landing() {
  return (
    <div className="-mx-6 -mt-20 bg-gray-50 min-h-screen">
      {/* Nav — frosted glass, liquid refraction */}
      <nav className="fixed top-0 inset-x-0 z-40 backdrop-blur-xl bg-gray-50/80 border-b border-gray-200/50 shadow-[inset_0_-1px_0_rgba(255,255,255,0.8)]">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-3">
          <span className="text-lg font-semibold tracking-tight text-gray-900">Shortlist</span>
          <div className="flex items-center gap-4">
            <Link href="/login" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
              Log in
            </Link>
            <Link
              href="/signup"
              className="rounded-full bg-gray-900 px-4 py-1.5 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
            >
              Sign up
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero — asymmetric, left-aligned (VARIANCE 8: centered BANNED) */}
      <section className="min-h-[100dvh] flex items-center">
        <div className="mx-auto max-w-[1200px] px-6 w-full grid md:grid-cols-[3fr_2fr] gap-16 items-center">
          <div>
            <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-5 animate-fade-up">
              Job search, automated
            </p>
            <h1 className="text-4xl md:text-6xl font-bold tracking-tighter leading-none text-gray-900 animate-fade-up" style={{ animationDelay: "0.05s" }}>
              127 jobs collected.<br />
              4 worth your time.
            </h1>
            <p className="mt-6 text-base md:text-lg text-gray-600 leading-relaxed max-w-[50ch] animate-fade-up" style={{ animationDelay: "0.1s" }}>
              Shortlist pulls from HN, LinkedIn, and ATS boards. Scores every role against your profile. Surfaces only what fits.
            </p>
            <div className="mt-10 flex gap-3 animate-fade-up" style={{ animationDelay: "0.15s" }}>
              <Link
                href="/signup"
                className="rounded-full bg-gray-900 px-7 py-3 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
              >
                Get started
              </Link>
              <a
                href="https://github.com/adamjramirez/shortlist"
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full border border-gray-300 px-7 py-3 text-sm font-medium text-gray-600 hover:bg-white transition-colors"
              >
                GitHub
              </a>
            </div>
            <p className="mt-4 font-mono text-xs text-gray-500 animate-fade-up" style={{ animationDelay: "0.2s" }}>
              Free. Bring your own API key. No credit card.
            </p>
          </div>
          {/* Right side — breathing space + subtle data hint */}
          <div className="hidden md:block">
            <div className="space-y-3 animate-fade-up" style={{ animationDelay: "0.3s" }}>
              {DEMO_JOBS.slice(0, 3).map((job) => (
                <div key={job.company} className="flex items-baseline gap-3 font-mono text-sm">
                  <span className={`font-semibold ${job.score >= 85 ? "text-emerald-600" : "text-gray-400"}`}>
                    {job.score}
                  </span>
                  <span className="text-gray-900">{job.title}</span>
                  <span className="text-gray-400 text-xs">{job.company}</span>
                </div>
              ))}
              <div className="flex items-baseline gap-3 font-mono text-sm text-gray-400">
                <span className="font-semibold">+1</span>
                <span>more match</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Demo — the centerpiece */}
      <section className="px-6 pb-32">
        <div className="mx-auto max-w-[900px] mb-12">
          <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-3 animate-fade-up" style={{ animationDelay: "0.2s" }}>
            Real output
          </p>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tighter text-gray-900 animate-fade-up" style={{ animationDelay: "0.22s" }}>
            This is what a run looks like
          </h2>
        </div>
        <DemoResults />
      </section>

      {/* CTA — asymmetric, left-aligned to match hero */}
      <section className="border-t border-gray-200/60">
        <div className="mx-auto max-w-[1200px] px-6 py-24 md:py-32 grid md:grid-cols-[3fr_2fr] gap-16 items-center">
          <div>
            <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-gray-900">
              Two minutes to set up.
            </h2>
            <p className="mt-3 text-gray-600 max-w-[45ch]">
              Upload your resume, paste a free Gemini API key, run your first search.
            </p>
            <div className="mt-8 flex gap-3">
              <Link
                href="/signup"
                className="rounded-full bg-gray-900 px-7 py-3 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
              >
                Get started
              </Link>
              <Link
                href="/login"
                className="rounded-full border border-gray-300 px-7 py-3 text-sm font-medium text-gray-600 hover:bg-white transition-colors"
              >
                Log in
              </Link>
            </div>
          </div>
          <div className="hidden md:block font-mono text-xs text-gray-400 space-y-1">
            <p>01 &mdash; Create account</p>
            <p>02 &mdash; Paste API key <span className="text-gray-300">(Gemini is free)</span></p>
            <p>03 &mdash; Upload resume</p>
            <p>04 &mdash; Click run</p>
          </div>
        </div>
      </section>
    </div>
  );
}

const PER_PAGE = 20;

function Dashboard() {
  const [profileData, setProfile] = useState<Profile | null>(null);
  const [resumeList, setResumes] = useState<Resume[]>([]);
  const [jobList, setJobs] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<JobStatusCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [minScore, setMinScore] = useState<number | undefined>(SCORE_VISIBLE);
  const [track, setTrack] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [runActive, setRunActive] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [p, r, j] = await Promise.all([
        profileApi.get(),
        resumesApi.list(),
        jobsApi.list({ min_score: minScore, track, user_status: statusFilter, page, per_page: PER_PAGE }),
      ]);
      setProfile(p);
      setResumes(r);
      setJobs(j.jobs);
      setTotal(j.total);
      if (j.counts) setCounts(j.counts);
    } finally {
      setLoading(false);
    }
  }, [minScore, track, statusFilter, page]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return <DashboardSkeleton />;
  }

  const needsOnboarding =
    !profileData?.fit_context || Object.keys(profileData.tracks).length === 0;

  if (needsOnboarding && profileData) {
    return <OnboardingChecklist profile={profileData} resumes={resumeList} />;
  }

  const tracks = profileData
    ? Object.entries(profileData.tracks).map(([key, val]) => ({
        key,
        title: (val as Record<string, unknown>)?.title as string || key,
      }))
    : [];

  const statusPills: { key: string | undefined; label: string; count?: number }[] = [
    { key: undefined, label: "All", count: counts ? counts.new + counts.saved + counts.applied + counts.skipped : undefined },
    { key: "new", label: "New", count: counts?.new },
    { key: "saved", label: "Saved", count: counts?.saved },
    { key: "applied", label: "Applied", count: counts?.applied },
    { key: "skipped", label: "Skipped", count: counts?.skipped },
  ];

  return (
    <div>
      {/* Header — data-led */}
      <div className="mb-6 animate-fade-up">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tighter text-gray-900">{total} matches</h1>
            {counts && (
              <p className="font-mono text-xs text-gray-400 mt-1">
                {counts.new > 0 && <span className="text-emerald-600">{counts.new} new</span>}
                {counts.new > 0 && counts.saved > 0 && <span> &middot; </span>}
                {counts.saved > 0 && <span>{counts.saved} saved</span>}
                {(counts.new > 0 || counts.saved > 0) && counts.applied > 0 && <span> &middot; </span>}
                {counts.applied > 0 && <span>{counts.applied} applied</span>}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={minScore ?? ""}
              onChange={(e) =>
                { const v = e.target.value ? Number(e.target.value) : undefined; setMinScore(v); setPage(1); analytics.filterChanged("min_score", v); }
              }
              className="rounded-full border border-gray-300 px-3 py-1.5 text-xs bg-white"
            >
              <option value={SCORE_VISIBLE}>{SCORE_VISIBLE}+</option>
              <option value={SCORE_STRONG}>{SCORE_STRONG}+ strong</option>
            </select>
            {tracks.length > 1 && (
              <select
                value={track ?? ""}
                onChange={(e) => { setTrack(e.target.value || undefined); setPage(1); analytics.filterChanged("track", e.target.value || "all"); }}
                className="rounded-full border border-gray-300 px-3 py-1.5 text-xs bg-white"
              >
                <option value="">All roles</option>
                {tracks.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.title}
                  </option>
                ))}
              </select>
            )}
            <RunButton onComplete={loadData} onProgress={loadData} onActiveChange={setRunActive} />
          </div>
        </div>

        {/* Status filter pills */}
        <div className="flex flex-wrap gap-1.5 mt-4">
          {statusPills.map((pill) => (
            <button
              key={pill.key ?? "all"}
              onClick={() => { setStatusFilter(pill.key); setPage(1); analytics.filterChanged("status", pill.key || "all"); }}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                statusFilter === pill.key
                  ? "bg-gray-900 text-white"
                  : "border border-gray-300 text-gray-600 hover:bg-white"
              }`}
            >
              {pill.label}{pill.count !== undefined && pill.count > 0 ? ` (${pill.count})` : ""}
            </button>
          ))}
        </div>
      </div>

      {/* Job list */}
      {jobList.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-gray-600">
            {runActive
              ? "Searching \u2014 matches will appear here as they\u2019re found\u2026"
              : "No jobs yet. Click \u201cRun now\u201d to start your first search."}
          </p>
        </div>
      ) : (
        <>
          <div>
            {jobList.map((job) => (
              <div key={job.id} className="border-b border-gray-200">
              <JobCard
                job={job}
                onStatusChange={() => loadData()}
                availableProviders={(() => {
                  const providers = new Set(profileData?.llm?.providers_with_keys || []);
                  if (profileData?.llm?.has_api_key) {
                    const m = profileData.llm.model || "gemini-2.0-flash";
                    if (m.startsWith("gemini")) providers.add("gemini");
                    else if (m.startsWith("gpt-") || m.startsWith("o1-")) providers.add("openai");
                    else if (m.startsWith("claude-")) providers.add("anthropic");
                  }
                  return Array.from(providers);
                })()}
              />
              </div>
            ))}
          </div>

          {/* Pagination */}
          {total > PER_PAGE && (() => {
            const totalPages = Math.ceil(total / PER_PAGE);
            return (
              <div className="mt-6 flex items-center justify-between">
                <p className="text-sm text-gray-500 font-mono">
                  {(page - 1) * PER_PAGE + 1}&ndash;{Math.min(page * PER_PAGE, total)} of {total}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => { setPage((p) => Math.max(1, p - 1)); window.scrollTo(0, 0); }}
                    disabled={page <= 1}
                    className="rounded-full border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    Prev
                  </button>
                  <span className="text-sm text-gray-500 font-mono">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); window.scrollTo(0, 0); }}
                    disabled={page >= totalPages}
                    className="rounded-full border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

export default function Home() {
  const { user, loading } = useAuth();

  if (loading) {
    return <DashboardSkeleton />;
  }

  return user ? <Dashboard /> : <Landing />;
}
