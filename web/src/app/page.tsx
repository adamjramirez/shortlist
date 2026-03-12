"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { track as analytics } from "@/lib/analytics";
import { profile as profileApi, resumes as resumesApi, jobs as jobsApi } from "@/lib/api";
import type { Profile, Resume, JobSummary } from "@/lib/types";
import OnboardingChecklist from "@/components/OnboardingChecklist";
import JobCard from "@/components/JobCard";
import RunButton from "@/components/RunButton";
import { SCORE_VISIBLE, SCORE_STRONG } from "@/lib/constants";

function Landing() {
  return (
    <div className="-mx-4 -mt-6">
      {/* Landing nav */}
      <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-gray-200 bg-white">
        <span className="text-lg font-semibold text-gray-900">Shortlist</span>
        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm text-gray-600 hover:text-gray-900">
            Log in
          </Link>
          <Link
            href="/signup"
            className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Sign up
          </Link>
        </div>
      </div>

      {/* Hero */}
      <section className="px-4 pt-16 pb-12 sm:pt-24 sm:pb-16 text-center">
        <h1 className="text-3xl sm:text-5xl font-bold tracking-tight text-gray-900 max-w-3xl mx-auto leading-tight">
          Stop scrolling job boards.
          <br className="hidden sm:block" />{" "}
          <span className="text-blue-600">Start reviewing matches.</span>
        </h1>
        <p className="mt-4 sm:mt-6 text-base sm:text-lg text-gray-600 max-w-xl mx-auto leading-relaxed">
          Shortlist collects jobs from various boards and sources, scores them against your
          profile, and shows you only what&apos;s worth your time.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row justify-center gap-3 sm:gap-4">
          <Link
            href="/signup"
            className="rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Get started — free
          </Link>
          <a
            href="https://github.com/adamjramirez/shortlist"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-gray-300 px-6 py-3 text-base font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            View on GitHub
          </a>
        </div>
        <p className="mt-3 text-xs text-gray-400">
          Free · Bring your own API key · No credit card
        </p>
      </section>

      {/* How it works */}
      <section className="px-4 py-12 sm:py-16 bg-white border-y border-gray-200">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-xl sm:text-2xl font-bold text-gray-900 text-center mb-8 sm:mb-10">
            How it works
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 sm:gap-8">
            {[
              {
                step: "1",
                title: "Upload your resume",
                desc: "Paste your resume and Shortlist generates your search profile — target roles, preferences, dealbreakers.",
              },
              {
                step: "2",
                title: "Run a search",
                desc: "One click. Hundreds of jobs collected, filtered, and scored against your profile in a few minutes.",
              },
              {
                step: "3",
                title: "Review matches",
                desc: "Scored results with reasoning, company intel, and tailored resumes for the ones worth applying to.",
              },
            ].map((item) => (
              <div key={item.step} className="text-center sm:text-left">
                <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-sm font-bold text-blue-600 mb-3">
                  {item.step}
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{item.title}</h3>
                <p className="text-sm text-gray-600 leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* What you need + cost */}
      <section className="px-4 py-12 sm:py-16">
        <div className="max-w-xl mx-auto">
          <h2 className="text-xl sm:text-2xl font-bold text-gray-900 text-center mb-6">
            What you need
          </h2>
          <ul className="space-y-3 text-sm text-gray-600">
            <li className="flex gap-3">
              <span className="text-blue-600 shrink-0">→</span>
              <span><strong className="text-gray-900">An LLM API key</strong> — Gemini, OpenAI, or Anthropic. Runs cost ~$0.25 with Gemini Flash.</span>
            </li>
            <li className="flex gap-3">
              <span className="text-blue-600 shrink-0">→</span>
              <span><strong className="text-gray-900">Your resume in LaTeX</strong> — needed for resume tailoring. Scoring works without it.</span>
            </li>
          </ul>
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-4 py-12 sm:py-16 bg-white border-t border-gray-200 text-center">
        <p className="text-gray-600 mb-6 max-w-md mx-auto">
          Set up takes about 2 minutes.
        </p>
        <div className="flex flex-col sm:flex-row justify-center gap-3 sm:gap-4">
          <Link
            href="/signup"
            className="rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Get started
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-gray-300 px-6 py-3 text-base font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Log in
          </Link>
        </div>
      </section>
    </div>
  );
}

function Dashboard() {
  const [profileData, setProfile] = useState<Profile | null>(null);
  const [resumeList, setResumes] = useState<Resume[]>([]);
  const [jobList, setJobs] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [minScore, setMinScore] = useState<number | undefined>(SCORE_VISIBLE);
  const [track, setTrack] = useState<string | undefined>(undefined);
  const [runActive, setRunActive] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [p, r, j] = await Promise.all([
        profileApi.get(),
        resumesApi.list(),
        jobsApi.list({ min_score: minScore, track }),
      ]);
      setProfile(p);
      setResumes(r);
      setJobs(j.jobs);
      setTotal(j.total);
    } finally {
      setLoading(false);
    }
  }, [minScore, track]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return <p className="mt-10 text-center text-gray-400">Loading...</p>;
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

  return (
    <div>
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Your matches</h1>
          <p className="text-sm text-gray-500">{total} jobs scored</p>
        </div>
        <RunButton onComplete={loadData} onProgress={loadData} onActiveChange={setRunActive} />
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={minScore ?? ""}
          onChange={(e) =>
            { const v = e.target.value ? Number(e.target.value) : undefined; setMinScore(v); analytics.filterChanged("min_score", v); }
          }
          className="rounded border border-gray-300 px-3 py-1.5 text-sm"
        >
          <option value={SCORE_VISIBLE}>{SCORE_VISIBLE}+ (matches)</option>
          <option value={SCORE_STRONG}>{SCORE_STRONG}+ (strong)</option>
        </select>
        {tracks.length > 1 && (
          <select
            value={track ?? ""}
            onChange={(e) => { setTrack(e.target.value || undefined); analytics.filterChanged("track", e.target.value || "all"); }}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm"
          >
            <option value="">All roles</option>
            {tracks.map((t) => (
              <option key={t.key} value={t.key}>
                {t.title}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Job list */}
      {jobList.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
          <p className="text-gray-500">
            {runActive
              ? "Searching — matches will appear here as they're found…"
              : "No jobs yet. Click \"Run now\" to start your first search."}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobList.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onStatusChange={() => loadData()}
              availableProviders={(() => {
                const providers = new Set(profileData?.llm?.providers_with_keys || []);
                // Main model's provider always has a key if has_api_key is true
                if (profileData?.llm?.has_api_key) {
                  const m = profileData.llm.model || "gemini-2.0-flash";
                  if (m.startsWith("gemini")) providers.add("gemini");
                  else if (m.startsWith("gpt-") || m.startsWith("o1-")) providers.add("openai");
                  else if (m.startsWith("claude-")) providers.add("anthropic");
                }
                return Array.from(providers);
              })()}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function Home() {
  const { user, loading } = useAuth();

  if (loading) {
    return <p className="mt-10 text-center text-gray-400">Loading...</p>;
  }

  return user ? <Dashboard /> : <Landing />;
}
