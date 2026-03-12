"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { profile as profileApi, resumes as resumesApi, jobs as jobsApi } from "@/lib/api";
import type { Profile, Resume, JobSummary } from "@/lib/types";
import OnboardingChecklist from "@/components/OnboardingChecklist";
import JobCard from "@/components/JobCard";
import RunButton from "@/components/RunButton";
import { SCORE_VISIBLE, SCORE_STRONG } from "@/lib/constants";

function Landing() {
  return (
    <div className="mx-auto mt-20 max-w-2xl text-center">
      <h1 className="text-4xl font-bold tracking-tight text-gray-900">
        AI-powered job search
      </h1>
      <p className="mt-4 text-lg text-gray-600">
        Score and rank job listings with AI. Get a daily brief of your best matches.
      </p>
      <div className="mt-8 flex justify-center gap-4">
        <Link
          href="/signup"
          className="rounded-md bg-blue-600 px-6 py-3 text-white hover:bg-blue-700"
        >
          Get started
        </Link>
        <Link
          href="/login"
          className="rounded-md border border-gray-300 px-6 py-3 text-gray-700 hover:bg-gray-50"
        >
          Log in
        </Link>
      </div>
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
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Your matches</h1>
          <p className="text-sm text-gray-500">{total} jobs scored</p>
        </div>
        <RunButton onComplete={loadData} onProgress={loadData} onActiveChange={setRunActive} />
      </div>

      {/* Filters */}
      <div className="mb-4 flex gap-3">
        <select
          value={minScore ?? ""}
          onChange={(e) =>
            setMinScore(e.target.value ? Number(e.target.value) : undefined)
          }
          className="rounded border border-gray-300 px-3 py-1.5 text-sm"
        >
          <option value={SCORE_VISIBLE}>{SCORE_VISIBLE}+ (matches)</option>
          <option value={SCORE_STRONG}>{SCORE_STRONG}+ (strong)</option>
        </select>
        {tracks.length > 1 && (
          <select
            value={track ?? ""}
            onChange={(e) => setTrack(e.target.value || undefined)}
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
