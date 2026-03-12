"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRequireAuth } from "@/lib/use-require-auth";
import {
  profile as profileApi,
  resumes as resumesApi,
  ApiError,
} from "@/lib/api";
import type { Profile, Resume } from "@/lib/types";
import {
  TrackForm,
  FiltersForm,
  jsonToTracks,
  tracksToJson,
  jsonToFilters,
  filtersToJson,
  defaultFilters,
} from "@/lib/profile-types";
import { track } from "@/lib/analytics";
import SectionCard from "@/components/SectionCard";
import TrackEditor from "@/components/TrackEditor";
import FiltersEditor from "@/components/FiltersEditor";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

const FIT_CONTEXT_PLACEHOLDER = `e.g. I'm a senior backend engineer with 8 years of Python experience. Looking for Staff+ roles at Series B–D startups…`;

const API_KEY_LINKS: Record<string, { label: string; url: string }> = {
  "gemini-2.0-flash": {
    label: "Get a Gemini key",
    url: "https://aistudio.google.com/apikey",
  },
  "gemini-2.5-flash": {
    label: "Get a Gemini key",
    url: "https://aistudio.google.com/apikey",
  },
  "gpt-4o-mini": {
    label: "Get an OpenAI key",
    url: "https://platform.openai.com/api-keys",
  },
  "claude-3-5-haiku-latest": {
    label: "Get an Anthropic key",
    url: "https://console.anthropic.com/settings/keys",
  },
};

export default function ProfilePage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [resumeList, setResumes] = useState<Resume[]>([]);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [generated, setGenerated] = useState(false);
  const toastTimer = useRef<NodeJS.Timeout | null>(null);

  // Form state
  const [fitContext, setFitContext] = useState("");
  const [tracks, setTracks] = useState<TrackForm[]>([]);
  const [filters, setFilters] = useState<FiltersForm>(defaultFilters());
  const [llmModel, setLlmModel] = useState("gemini-2.0-flash");
  const [apiKey, setApiKey] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [substackSid, setSubstackSid] = useState("");
  // Per-provider extra keys (for cover letters with different models)
  const [extraKeys, setExtraKeys] = useState<Record<string, string>>({});
  const [providersWithKeys, setProvidersWithKeys] = useState<string[]>([]);

  const hasProfile =
    !!fitContext || tracks.length > 0 || Object.keys(profile?.tracks || {}).length > 0;

  useEffect(() => {
    if (authLoading || !user) return;
    Promise.all([profileApi.get(), resumesApi.list()]).then(([p, r]) => {
      setProfile(p);
      setResumes(r);
      setFitContext(p.fit_context);
      setTracks(jsonToTracks(p.tracks));
      setFilters(jsonToFilters(p.filters));
      setLlmModel(p.llm?.model || "gemini-2.0-flash");
      setHasApiKey(!!p.llm?.has_api_key);
      setProvidersWithKeys(p.llm?.providers_with_keys || []);
      setSubstackSid(p.substack_sid || "");
    });
  }, [user, authLoading]);

  const markDirty = useCallback(
    <T,>(setter: React.Dispatch<React.SetStateAction<T>>) =>
      (val: T | ((prev: T) => T)) => {
        setter(val);
        setDirty(true);
        setError("");
      },
    [],
  );

  const showToast = (msg: string) => {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 3000);
  };

  // Save API key immediately so it's available for generation
  const saveApiKey = async () => {
    if (!apiKey && !llmModel && Object.keys(extraKeys).length === 0) return;
    const llm: Record<string, unknown> = { model: llmModel };
    if (apiKey) llm.api_key = apiKey;
    // Include any extra provider keys
    const nonEmpty = Object.fromEntries(
      Object.entries(extraKeys).filter(([, v]) => v.trim())
    );
    if (Object.keys(nonEmpty).length > 0) llm.provider_keys = nonEmpty;
    try {
      const updated = await profileApi.update({ llm });
      setProfile(updated);
      setHasApiKey(!!updated.llm?.has_api_key);
      setProvidersWithKeys(updated.llm?.providers_with_keys || []);
      setApiKey("");
      setExtraKeys({});
      showToast("API key saved ✓");
      // Track which providers got keys
      const mainProvider = llmModel.startsWith("gemini") ? "gemini"
        : llmModel.startsWith("gpt-") || llmModel.startsWith("o1-") ? "openai"
        : llmModel.startsWith("claude-") ? "anthropic" : "unknown";
      if (apiKey) track.apiKeySaved(mainProvider);
      for (const p of Object.keys(nonEmpty)) track.apiKeySaved(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save key");
    }
  };

  const handleAnalyze = async () => {
    if (resumeList.length === 0) return;
    setAnalyzing(true);
    setError("");

    // Save API key first if provided
    if (apiKey) await saveApiKey();

    try {
      const result = await profileApi.generate(resumeList[0].id);
      setFitContext(result.fit_context);
      setTracks(jsonToTracks(result.tracks));
      setFilters(jsonToFilters(result.filters));
      setGenerated(true);
      track.profileAnalyzed(resumeList[0].id);
      setDirty(true);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Analysis failed";
      setError(msg);
      track.profileAnalysisFailed(msg);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    setToast("");
    try {
      for (const t of tracks) {
        if (!t.title.trim()) {
          setError("Each role needs a title");
          setSaving(false);
          return;
        }
        if (t.search_queries.length === 0) {
          setError(`"${t.title}" needs at least one search query`);
          setSaving(false);
          return;
        }
      }

      const llm: Record<string, unknown> = { model: llmModel };
      if (apiKey) llm.api_key = apiKey;
      const nonEmpty = Object.fromEntries(
        Object.entries(extraKeys).filter(([, v]) => v.trim())
      );
      if (Object.keys(nonEmpty).length > 0) llm.provider_keys = nonEmpty;

      const payload: Record<string, unknown> = {
        fit_context: fitContext,
        tracks: tracksToJson(tracks),
        filters: filtersToJson(filters),
        llm,
      };
      if (substackSid) payload.substack_sid = substackSid;

      const updated = await profileApi.update(payload);
      setProfile(updated);
      setTracks(jsonToTracks(updated.tracks));
      setFilters(jsonToFilters(updated.filters));
      setHasApiKey(!!updated.llm?.has_api_key);
      setProvidersWithKeys(updated.llm?.providers_with_keys || []);
      setApiKey("");
      setExtraKeys({});
      setDirty(false);
      setGenerated(false);
      showToast("Profile saved ✓");
      track.profileSaved();
    } catch (err) {
      setToast("");
      const msg = err instanceof ApiError ? err.detail : "Failed to save";
      setError(msg);
      track.profileSaveFailed(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const resume = await resumesApi.upload(file);
      setResumes((prev) => [resume, ...prev]);
      track.resumeUploaded(file.name);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Upload failed";
      setError(msg);
      track.resumeUploadFailed(file.name, msg);
    }
    e.target.value = "";
  };

  const handleDeleteResume = async (id: number) => {
    await resumesApi.delete(id);
    setResumes((prev) => prev.filter((r) => r.id !== id));
  };

  if (!profile) {
    return <p className="mt-10 text-center text-gray-400">Loading...</p>;
  }

  const keyLink = API_KEY_LINKS[llmModel];
  const canAnalyze = resumeList.length > 0 && (hasApiKey || !!apiKey);

  return (
    <div className="mx-auto max-w-2xl space-y-6 pb-24">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Profile setup</h1>
        <p className="mt-1 text-sm text-gray-500">
          Upload your resume and we&apos;ll set up your job search
          automatically.
        </p>
      </div>

      {/* ── Phase A: The two manual inputs ── */}

      {/* 1. Resume */}
      <SectionCard
        step={1}
        title="Upload your resume"
        subtitle="We'll analyze this to understand your background and generate your search profile."
      >
        <div className="space-y-3">
          {resumeList.length > 0 && (
            <div className="space-y-2">
              {resumeList.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-2.5"
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-gray-400">📄</span>
                    <span className="font-medium text-gray-700">
                      {r.filename}
                    </span>
                    {r.track && (
                      <span className="rounded-md bg-blue-50 px-2 py-0.5 text-xs text-blue-600">
                        {r.track}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleDeleteResume(r.id)}
                    className="rounded-md px-2 py-1 text-xs text-gray-400 hover:bg-red-50 hover:text-red-600"
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          )}
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-2.5 text-sm text-gray-500 hover:border-gray-400 hover:text-gray-700">
            <span>+</span> Upload .tex file
            <input
              type="file"
              accept=".tex"
              onChange={handleUpload}
              className="hidden"
            />
          </label>
        </div>
      </SectionCard>

      {/* 2. AI Provider */}
      <SectionCard
        step={2}
        title="Connect your AI provider"
        subtitle="We use your API key to analyze your resume and score jobs. You pay the provider directly — typical cost is ~$0.01 per run."
      >
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Model
            </label>
            <select
              value={llmModel}
              onChange={(e) => {
                setLlmModel(e.target.value);
                setDirty(true);
              }}
              className={inputClass}
            >
              <option value="gemini-2.0-flash">
                Gemini 2.0 Flash (recommended — fast &amp; cheap)
              </option>
              <option value="gemini-2.5-flash">
                Gemini 2.5 Flash (smarter, slower)
              </option>
              <option value="gpt-4o-mini">GPT-4o Mini</option>
              <option value="claude-3-5-haiku-latest">Claude 3.5 Haiku</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              API key{" "}
              {hasApiKey && (
                <span className="font-normal text-green-600">✓ saved</span>
              )}
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                hasApiKey
                  ? "••••••• (leave blank to keep current)"
                  : "Paste your API key"
              }
              className={inputClass}
            />
            {keyLink && (
              <p className="mt-1.5 text-xs text-gray-400">
                Don&apos;t have one?{" "}
                <a
                  href={keyLink.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:text-blue-600"
                >
                  {keyLink.label} →
                </a>
              </p>
            )}
          </div>

          {/* Extra provider keys for cover letters */}
          <details className="group">
            <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
              Add keys for other providers (for cover letters)
              {providersWithKeys.length > 1 && (
                <span className="ml-2 text-xs text-green-600">
                  {providersWithKeys.length} providers configured
                </span>
              )}
            </summary>
            <div className="mt-3 space-y-3 pl-1">
              <p className="text-xs text-gray-400">
                Different AI models write differently. Add keys for other
                providers to choose which model generates your cover letters.
              </p>
              {[
                { provider: "gemini", label: "Gemini", url: "https://aistudio.google.com/apikey" },
                { provider: "openai", label: "OpenAI", url: "https://platform.openai.com/api-keys" },
                { provider: "anthropic", label: "Anthropic (Claude)", url: "https://console.anthropic.com/settings/keys" },
              ]
                .filter(({ provider }) => {
                  // Don't show the field for the provider that matches the main model
                  const mainProvider = llmModel.startsWith("gemini") ? "gemini"
                    : llmModel.startsWith("gpt-") || llmModel.startsWith("o1-") ? "openai"
                    : llmModel.startsWith("claude-") ? "anthropic" : "";
                  return provider !== mainProvider;
                })
                .map(({ provider, label, url }) => (
                  <div key={provider}>
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      {label} API key{" "}
                      {providersWithKeys.includes(provider) && (
                        <span className="font-normal text-green-600">✓ saved</span>
                      )}
                    </label>
                    <input
                      type="password"
                      value={extraKeys[provider] || ""}
                      onChange={(e) => {
                        setExtraKeys((prev) => ({ ...prev, [provider]: e.target.value }));
                        setDirty(true);
                      }}
                      placeholder={
                        providersWithKeys.includes(provider)
                          ? "••••••• (leave blank to keep current)"
                          : `Paste ${label} key`
                      }
                      className={inputClass + " text-xs"}
                    />
                    <p className="mt-0.5 text-xs text-gray-400">
                      <a href={url} target="_blank" rel="noopener noreferrer"
                         className="text-blue-500 hover:text-blue-600">
                        Get a {label} key →
                      </a>
                    </p>
                  </div>
                ))}
            </div>
          </details>
        </div>
      </SectionCard>

      {/* ── Analyze button ── */}
      <div className="flex flex-col items-center gap-3 py-2">
        <button
          onClick={handleAnalyze}
          disabled={!canAnalyze || analyzing}
          className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-6 py-3.5 text-sm font-semibold text-white shadow-md transition hover:from-blue-700 hover:to-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {analyzing ? (
            <span className="flex items-center justify-center gap-2">
              <svg
                className="h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                />
              </svg>
              Analyzing your resume…
            </span>
          ) : (
            "✨ Analyze my resume"
          )}
        </button>
        {!canAnalyze && (
          <p className="text-xs text-gray-400">
            {resumeList.length === 0 && !hasApiKey
              ? "Upload a resume and add your API key to get started"
              : resumeList.length === 0
                ? "Upload a resume first"
                : "Add your API key first"}
          </p>
        )}
      </div>

      {/* ── Phase B: AI-generated (or existing) profile ── */}
      {(hasProfile || generated) && (
        <>
          {generated && (
            <div className="flex items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-2.5">
              <span className="text-sm">✨</span>
              <p className="text-sm text-indigo-700">
                Profile generated from your resume. Review and edit anything
                below, then save.
              </p>
            </div>
          )}

          {/* 3. Fit context */}
          <SectionCard
            step={3}
            title="What you're looking for"
            subtitle="This is the main input to the AI scorer. Edit freely — the more specific, the better your matches."
          >
            <textarea
              value={fitContext}
              onChange={(e) => {
                setFitContext(e.target.value);
                setDirty(true);
                setGenerated(false);
              }}
              rows={8}
              placeholder={FIT_CONTEXT_PLACEHOLDER}
              className={`${inputClass} placeholder:text-gray-300`}
            />
          </SectionCard>

          {/* 4. Tracks */}
          <SectionCard
            step={4}
            title="Roles to search for"
            subtitle="Each role gets its own search queries. Edit titles, add queries, or remove roles that don't fit."
          >
            <TrackEditor
              tracks={tracks}
              onChange={(t) => {
                setTracks(t);
                setDirty(true);
                setError("");
              }}
              resumes={resumeList}
            />
          </SectionCard>

          {/* 5. Filters */}
          <SectionCard
            step={5}
            title="Hard filters"
            subtitle="Jobs that fail these are automatically rejected before scoring."
          >
            <FiltersEditor filters={filters} onChange={markDirty(setFilters)} />
          </SectionCard>

          {/* 6. Advanced */}
          <SectionCard
            step={6}
            title="Advanced"
            subtitle="Optional settings for power users."
          >
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                NextPlay Substack cookie{" "}
                {substackSid && (
                  <span className="font-normal text-green-600">✓ set</span>
                )}
              </label>
              <input
                type="password"
                value={substackSid}
                onChange={(e) => {
                  setSubstackSid(e.target.value);
                  setDirty(true);
                }}
                placeholder="Paste your substack.sid cookie to include paid content"
                className={inputClass}
              />
              <p className="mt-1.5 text-xs text-gray-400">
                Optional. Enables access to paid NextPlay newsletter content for
                additional job sources. Find it in your browser cookies for
                substack.com.
              </p>
            </div>
          </SectionCard>

          {/* Re-analyze option */}
          <div className="text-center">
            <button
              onClick={handleAnalyze}
              disabled={!canAnalyze || analyzing}
              className="text-sm text-gray-400 hover:text-blue-600 disabled:opacity-40"
            >
              {analyzing ? "Analyzing…" : "✨ Re-analyze from resume"}
            </button>
          </div>
        </>
      )}

      {/* Sticky save bar */}
      {(hasProfile || generated) && (
        <div className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-200 bg-white/95 backdrop-blur-sm">
          <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
            <div className="flex items-center gap-2">
              {dirty && (
                <>
                  <span className="h-2 w-2 rounded-full bg-amber-400" />
                  <span className="text-sm text-gray-500">
                    Unsaved changes
                  </span>
                </>
              )}
              {toast && (
                <span className="text-sm font-medium text-green-600">
                  {toast}
                </span>
              )}
              {error && (
                <span className="text-sm text-red-600">{error}</span>
              )}
            </div>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save profile"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
