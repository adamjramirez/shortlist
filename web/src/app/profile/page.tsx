"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRequireAuth } from "@/lib/use-require-auth";
import {
  profile as profileApi,
  resumes as resumesApi,
  ApiError,
} from "@/lib/api";
import type { AutoRunConfig, Profile, Resume } from "@/lib/types";
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
import ResumeUploader from "@/components/ResumeUploader";
import AiProviderForm from "@/components/AiProviderForm";
import AnalyzeButton from "@/components/AnalyzeButton";
import TrackEditor from "@/components/TrackEditor";
import FiltersEditor from "@/components/FiltersEditor";
import SaveBar from "@/components/SaveBar";
import AutoRunSettings from "@/components/AutoRunSettings";
import { ProfileSkeleton } from "@/components/Skeleton";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

const FIT_CONTEXT_PLACEHOLDER = `e.g. I'm a senior backend engineer with 8 years of Python experience. Looking for Staff+ roles at Series B–D startups…`;

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
  const [extraKeys, setExtraKeys] = useState<Record<string, string>>({});
  const [providersWithKeys, setProvidersWithKeys] = useState<string[]>([]);
  const [autoRun, setAutoRun] = useState<AutoRunConfig>({
    enabled: false,
    interval_h: 12,
    next_run_at: null,
    consecutive_failures: 0,
  });
  const [autoRunDirty, setAutoRunDirty] = useState(false);

  const hasProfile =
    !!fitContext || tracks.length > 0 || Object.keys(profile?.tracks || {}).length > 0;

  // ── Data loading ──

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
      if (p.auto_run) setAutoRun(p.auto_run);
    });
  }, [user, authLoading]);

  // ── Helpers ──

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

  // ── Handlers ──

  const saveApiKey = async () => {
    if (!apiKey && !llmModel && Object.keys(extraKeys).length === 0) return;
    const llm: Record<string, unknown> = { model: llmModel };
    if (apiKey) llm.api_key = apiKey;
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
      // Only send auto_run when the user changed it — avoids resetting next_run_at on every save
      if (autoRunDirty) {
        payload.auto_run = { enabled: autoRun.enabled, interval_h: autoRun.interval_h };
      }

      const updated = await profileApi.update(payload);
      setProfile(updated);
      setTracks(jsonToTracks(updated.tracks));
      setFilters(jsonToFilters(updated.filters));
      setHasApiKey(!!updated.llm?.has_api_key);
      setProvidersWithKeys(updated.llm?.providers_with_keys || []);
      setApiKey("");
      setExtraKeys({});
      if (updated.auto_run) setAutoRun(updated.auto_run);
      setDirty(false);
      setAutoRunDirty(false);
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

  // ── Render ──

  if (!profile) return <ProfileSkeleton />;

  const canAnalyze = resumeList.length > 0 && (hasApiKey || !!apiKey);

  return (
    <div className="mx-auto max-w-2xl pb-28">
      {/* Page header */}
      <div className="mb-8 animate-fade-up">
        <p className="font-mono text-xs tracking-widest uppercase text-emerald-600 mb-2">Profile</p>
        <h1 className="text-2xl font-bold tracking-tighter text-gray-900">Profile setup</h1>
        <p className="mt-1 text-sm text-gray-500">
          Upload your resume and we&apos;ll set up your job search automatically.
        </p>
      </div>

      {/* ── All sections ── */}
      <div className="divide-y divide-gray-200/60">
        <SectionCard
          step={1}
          title="Upload your resume"
          subtitle="We'll analyze this to understand your background and generate your search profile."
        >
          <ResumeUploader
            resumes={resumeList}
            onUpload={handleUpload}
            onDelete={handleDeleteResume}
          />
        </SectionCard>

        <SectionCard
          step={2}
          title="Connect your AI provider"
          subtitle="We use your API key to analyze your resume and score jobs. You pay the provider directly — typical cost is ~$0.01 per run."
        >
          <AiProviderForm
            llmModel={llmModel}
            onModelChange={(m) => { setLlmModel(m); setDirty(true); }}
            apiKey={apiKey}
            onApiKeyChange={setApiKey}
            hasApiKey={hasApiKey}
            extraKeys={extraKeys}
            onExtraKeyChange={(provider, key) => {
              setExtraKeys((prev) => ({ ...prev, [provider]: key }));
              setDirty(true);
            }}
            providersWithKeys={providersWithKeys}
          />
        </SectionCard>

        <div className="py-6">
          <AnalyzeButton
            canAnalyze={canAnalyze}
            analyzing={analyzing}
            hasResume={resumeList.length > 0}
            hasApiKey={hasApiKey || !!apiKey}
            onAnalyze={handleAnalyze}
          />
        </div>

        {(hasProfile || generated) && <>
          {generated && (
            <div className="py-4 px-1">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5">
                <p className="text-sm text-emerald-700">
                  ✓ Profile generated from your resume. Review and edit below, then save.
                </p>
              </div>
            </div>
          )}

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

          <SectionCard
            step={4}
            title="Roles to search for"
            subtitle="Each role gets its own search queries. Edit titles, add queries, or remove roles that don't fit."
          >
            <TrackEditor
              tracks={tracks}
              onChange={(t) => { setTracks(t); setDirty(true); setError(""); }}
              resumes={resumeList}
            />
          </SectionCard>

          <SectionCard
            step={5}
            title="Hard filters"
            subtitle="Jobs that fail these are automatically rejected before scoring."
          >
            <FiltersEditor filters={filters} onChange={markDirty(setFilters)} />
          </SectionCard>

          <SectionCard
            step={6}
            title="Auto-run"
            subtitle="Run automatically on a schedule so new jobs appear in your inbox."
          >
            <AutoRunSettings
              autoRun={autoRun}
              onChange={(update) => {
                setAutoRun((prev) => ({ ...prev, ...update }));
                setDirty(true);
                setAutoRunDirty(true);
              }}
            />
          </SectionCard>

          <SectionCard
            step={7}
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
                onChange={(e) => { setSubstackSid(e.target.value); setDirty(true); }}
                placeholder="Paste your substack.sid cookie to include paid content"
                className={inputClass}
              />
              <p className="mt-1.5 text-xs text-gray-400">
                Optional. Enables access to paid NextPlay newsletter content for
                additional job sources. Find it in your browser cookies for substack.com.
              </p>
            </div>
          </SectionCard>
        </>}
      </div>

      {/* Sticky save bar */}
      {(hasProfile || generated) && (
        <SaveBar
          dirty={dirty}
          saving={saving}
          toast={toast}
          error={error}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
