"use client";

import { useEffect } from "react";
import Link from "next/link";
import type { Profile, Resume } from "@/lib/types";
import { track } from "@/lib/analytics";

interface Props {
  profile: Profile;
  resumes: Resume[];
}

interface CheckItem {
  label: string;
  done: boolean;
  href?: string;
}

export default function OnboardingChecklist({ profile, resumes }: Props) {
  const checks: CheckItem[] = [
    {
      label: "Describe what you're looking for",
      done: !!profile.fit_context,
    },
    {
      label: "Add a role you're searching for",
      done: Object.keys(profile.tracks).length > 0,
    },
    {
      label: "Upload your resume",
      done: resumes.length > 0,
    },
    {
      label: "Connect your AI provider",
      done: !!profile.llm?.has_api_key,
      href: "/getting-started",
    },
    {
      label: "Set your location and salary preferences",
      done: !!(
        profile.filters?.location &&
        ((profile.filters.location as Record<string, unknown>)?.local_zip ||
          (profile.filters.location as Record<string, unknown>)?.remote)
      ),
    },
  ];

  const done = checks.filter((c) => c.done).length;
  const allDone = done === checks.length;

  useEffect(() => {
    const firstIncomplete = checks.find((c) => !c.done);
    if (firstIncomplete) {
      track.onboardingStepViewed(firstIncomplete.label);
    }
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mx-auto max-w-lg animate-fade-up">
      <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-3">
        {allDone ? "Ready" : "Setup"}
      </p>
      <h2 className="text-2xl font-bold tracking-tighter text-gray-900">
        {allDone ? "You're all set" : "Let's get you set up"}
      </h2>
      <p className="mt-2 text-sm text-gray-600">
        {allDone
          ? "Your profile is ready. Run your first search to see matches."
          : `${done} of ${checks.length} steps complete`}
      </p>

      {/* Progress bar */}
      <div className="mt-6 h-1 overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-emerald-600 transition-all duration-300"
          style={{ width: `${(done / checks.length) * 100}%` }}
        />
      </div>

      <div className="mt-8 divide-y divide-gray-200/60">
        {checks.map((check, i) => (
          <div key={check.label} className="flex items-start gap-3 py-4">
            <span className="font-mono text-xs text-gray-300 w-5 text-right shrink-0 pt-0.5">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div
              className={`flex-1 ${check.done ? "text-gray-400" : "text-gray-900"}`}
            >
              <span className={`text-sm ${check.done ? "line-through" : "font-medium"}`}>
                {check.label}
              </span>
              {check.href && !check.done && (
                <Link
                  href={check.href}
                  className="ml-2 text-sm text-emerald-600 hover:text-emerald-700"
                >
                  how to get a key
                </Link>
              )}
            </div>
            {check.done && (
              <svg className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            )}
          </div>
        ))}
      </div>

      <div className="mt-8">
        <Link
          href={allDone ? "/" : "/profile"}
          className="inline-flex rounded-full bg-gray-900 px-7 py-3 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
        >
          {allDone ? "Run your first search" : "Set up your profile"}
        </Link>
      </div>
    </div>
  );
}
