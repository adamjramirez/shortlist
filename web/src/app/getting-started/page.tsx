"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { track } from "@/lib/analytics";

interface ProviderInfo {
  id: string;
  name: string;
  model: string;
  free: boolean;
  cost: string;
  bestFor: string;
  keyUrl: string;
  keyUrlLabel: string;
  steps: string[];
  recommended?: boolean;
}

const PROVIDERS: ProviderInfo[] = [
  {
    id: "gemini",
    name: "Gemini",
    model: "Gemini 2.0 Flash",
    free: true,
    cost: "$0/month",
    bestFor: "Most users. Fast, free, great quality.",
    keyUrl: "https://aistudio.google.com/apikey",
    keyUrlLabel: "aistudio.google.com/apikey",
    steps: [
      "Go to aistudio.google.com/apikey",
      "Sign in with your Google account",
      "Click Create API Key -- select any project (or create one)",
      "Copy the key, paste it on your profile page",
    ],
    recommended: true,
  },
  {
    id: "openai",
    name: "OpenAI",
    model: "GPT-4o Mini",
    free: false,
    cost: "~$1-3/month",
    bestFor: "Users who already have an OpenAI account.",
    keyUrl: "https://platform.openai.com/api-keys",
    keyUrlLabel: "platform.openai.com/api-keys",
    steps: [
      "Go to platform.openai.com/api-keys",
      "Sign up or log in",
      "Settings, Billing, add a payment method ($5 minimum)",
      "Create new secret key, copy it, paste on your profile page",
    ],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    model: "Claude 3.5 Haiku",
    free: false,
    cost: "~$1-3/month",
    bestFor: "Best writing quality for cover letters.",
    keyUrl: "https://console.anthropic.com",
    keyUrlLabel: "console.anthropic.com",
    steps: [
      "Go to console.anthropic.com",
      "Sign up or log in",
      "Settings, Billing, add credits ($5 minimum)",
      "Settings, API Keys, Create Key, copy it, paste on your profile page",
    ],
  },
];

export default function GettingStartedPage() {
  const [expanded, setExpanded] = useState<string | null>("gemini");

  useEffect(() => {
    track.gettingStartedViewed();
  }, []);

  return (
    <div className="-mx-6 -mt-20 bg-gray-50 min-h-screen">
      {/* Nav */}
      <nav className="fixed top-0 inset-x-0 z-40 backdrop-blur-xl bg-gray-50/80 border-b border-gray-200/50 shadow-[inset_0_-1px_0_rgba(255,255,255,0.8)]">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-3">
          <Link href="/" className="text-lg font-semibold tracking-tight text-gray-900 hover:text-gray-700 transition-colors">
            Shortlist
          </Link>
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

      <div className="mx-auto max-w-[900px] px-6 pt-28 pb-24">
        {/* Header — left-aligned */}
        <div className="mb-16 animate-fade-up">
          <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-4">Setup guide</p>
          <h1 className="text-3xl md:text-4xl font-bold tracking-tighter text-gray-900">
            Get your API key
          </h1>
          <p className="mt-4 text-base text-gray-500 leading-relaxed max-w-[55ch]">
            Shortlist uses AI to score jobs and write cover letters. You bring your own
            API key. Your data goes directly to the provider, you control costs.
            Most users spend <span className="text-gray-900 font-medium">$0/month</span>.
          </p>
        </div>

        {/* Provider list — divide-y, no cards */}
        <div className="divide-y divide-gray-200/60 animate-fade-up" style={{ animationDelay: "0.1s" }}>
          {PROVIDERS.map((provider) => {
            const isOpen = expanded === provider.id;
            return (
              <div key={provider.id}>
                <button
                  onClick={() => {
                    const next = isOpen ? null : provider.id;
                    setExpanded(next);
                    if (next) track.gettingStartedProviderExpanded(provider.id);
                  }}
                  className="w-full text-left py-5 grid grid-cols-[1fr_auto_1rem] gap-x-6 items-center hover:bg-gray-100/50 -mx-3 px-3 rounded-lg transition-colors cursor-pointer"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-3">
                      <span className="font-medium text-gray-900">{provider.name}</span>
                      {provider.recommended && (
                        <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-600">
                          Recommended
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-0.5">{provider.bestFor}</p>
                  </div>
                  <span className="font-mono text-sm text-gray-400">{provider.cost}</span>
                  <svg
                    className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                    fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {isOpen && (
                  <div className="pb-6 animate-fade-up" style={{ animationDuration: "0.2s" }}>
                    <div className="space-y-4 pl-3">
                      <p className="text-sm text-gray-500">
                        <span className="text-gray-400">Model:</span> {provider.model}
                      </p>

                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-widest text-gray-400 mb-3">Steps</p>
                        <div className="space-y-2.5">
                          {provider.steps.map((step, si) => (
                            <div key={si} className="flex gap-3 text-sm">
                              <span className="font-mono text-gray-300 shrink-0 w-5 text-right">{si + 1}</span>
                              {si === 0 ? (
                                <p className="text-gray-600">
                                  Go to{" "}
                                  <a
                                    href={provider.keyUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-emerald-600 underline underline-offset-2 hover:text-emerald-700"
                                  >
                                    {provider.keyUrlLabel}
                                  </a>
                                </p>
                              ) : (
                                <p className="text-gray-600">{step}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* FAQ — border-t dividers, no cards */}
        <div className="mt-20 animate-fade-up" style={{ animationDelay: "0.2s" }}>
          <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-8">Common questions</p>
          <div className="divide-y divide-gray-200/60">
            {[
              {
                q: "Is my API key safe?",
                a: "Your key is encrypted at rest and never shared. Shortlist sends your data directly to the AI provider you choose.",
              },
              {
                q: "How much will it cost?",
                a: "A typical run scores ~50 jobs. With Gemini, that's free (1,500 requests/day). With OpenAI or Anthropic, roughly $0.01-0.05 per run.",
              },
              {
                q: "Can I switch providers later?",
                a: "Yes, anytime from your profile. You can add keys for multiple providers and use different models for scoring vs. cover letters.",
              },
            ].map((faq) => (
              <div key={faq.q} className="py-5">
                <h3 className="font-medium text-gray-900">{faq.q}</h3>
                <p className="mt-1.5 text-sm text-gray-500 leading-relaxed max-w-[65ch]">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="mt-20 animate-fade-up" style={{ animationDelay: "0.3s" }}>
          <p className="text-gray-500 mb-6">
            Got your key? Create an account, then paste it on your profile page.
          </p>
          <div className="flex gap-3">
            <Link
              href="/signup"
              onClick={() => track.gettingStartedCtaClicked()}
              className="rounded-full bg-gray-900 px-7 py-3 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98]"
            >
              Create account
            </Link>
            <Link
              href="/login"
              className="rounded-full border border-gray-300 px-7 py-3 text-sm font-medium text-gray-600 hover:bg-white transition-colors"
            >
              Log in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
