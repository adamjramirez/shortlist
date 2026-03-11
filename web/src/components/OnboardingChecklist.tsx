"use client";

import Link from "next/link";
import type { Profile, Resume } from "@/lib/types";

interface Props {
  profile: Profile;
  resumes: Resume[];
}

interface CheckItem {
  label: string;
  done: boolean;
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

  return (
    <div className="mx-auto max-w-lg">
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-900">
          {allDone ? "You're all set!" : "Let's get you set up"}
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          {allDone
            ? "Your profile is ready. Run your first search to see matches."
            : `${done} of ${checks.length} steps complete`}
        </p>

        {/* Progress bar */}
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-gray-100">
          <div
            className="h-full rounded-full bg-blue-600 transition-all duration-300"
            style={{ width: `${(done / checks.length) * 100}%` }}
          />
        </div>

        <ul className="mt-5 space-y-3">
          {checks.map((check) => (
            <li key={check.label} className="flex items-center gap-3">
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                  check.done
                    ? "bg-blue-600 text-white"
                    : "border-2 border-gray-200"
                }`}
              >
                {check.done && "✓"}
              </span>
              <span
                className={`text-sm ${check.done ? "text-gray-400" : "text-gray-700"}`}
              >
                {check.label}
              </span>
            </li>
          ))}
        </ul>

        <Link
          href={allDone ? "/" : "/profile"}
          className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          {allDone ? "Run your first search →" : "Set up your profile →"}
        </Link>
      </div>
    </div>
  );
}
