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
import FitContextExampleDrawer from "@/components/FitContextExampleDrawer";
import { ProfileSkeleton } from "@/components/Skeleton";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

const FIT_CONTEXT_PLACEHOLDER = `e.g. I'm a senior backend engineer with 8 years of Python experience. Looking for Staff+ roles at Series B–D startups…`;

const FIT_CONTEXT_EXAMPLE = `I am a Director of Platform Engineering at a Series D B2B SaaS company, looking to move into a VP Engineering or CTO role at an AI-native company. My current company is treating AI as a feature checkbox on a legacy product — that's not where I want to spend the next five years. I need to be inside a team where AI is load-bearing infrastructure, not a UI veneer.

TARGET ROLE & LEVEL
- Primary: VP of Engineering — Series B to Pre-IPO
- Secondary: CTO — Series A to Series C (full technical ownership)
- Also open to: Head of AI Engineering, VP Platform + AI, SVP Engineering
- Not interested in: IC roles, pure research, ML-researcher-adjacent, thought leadership / conference circuit

WHAT "AI-NATIVE" MEANS (this is the filter)
The company must meet at least 3 of these 5:
1. AI is in the critical path of the product — not a feature bolted on
2. They have evaluation systems: rubrics, golden datasets, regression testing for AI output quality
3. Cost and token economics is a real engineering concern (not "just use GPT-4 for everything")
4. Engineering workflow is agent-native (not "engineers use Copilot sometimes")
5. The eng leader would be expected to evolve the AI architecture, not just manage headcount

Companies "adding AI features" to traditional products are not a fit.

COMPENSATION
- Total target: $350K–$600K (base $250K–$350K + bonus 15–30% + equity $100K–$300K+)
- Below $300K total is not viable
- Equity structure matters — need change-of-control protection
- Remote-first preferred, hybrid acceptable

WHO I AM AND WHAT I'VE BUILT
Current role (since 2023): Director of Platform Engineering. ~12-person org across US + Canada + offshore. Owning the core platform roadmap, cloud-infra budget, and developer-productivity initiatives. Promoted Staff Engineer → EM → Director in ~3 years on delivery and org impact.

Selected proof points:
- Migrated a legacy monolith to event-driven microservices on schedule and under budget — the project had been attempted twice before and stalled both times
- Doubled deploy frequency (3 → 9 per week) by rebuilding the CI/CD path with automated canary + rollback
- Stood up a platform team from scratch — 6 engineers, internal tooling cut feature time-to-market by ~40%
- Redesigned the on-call rotation; sev-1 alert volume dropped 60% in six months without adding headcount

AI work alongside the day job: running a small AI observability side project — tracks eval quality, cost, and latency for LLM pipelines across providers. ~200 teams using it. Built the full stack myself: multi-provider routing, rubric engine, golden-dataset regression suite, per-team cost-budget enforcement. In production for paying customers for 14 months. This is where most of my hands-on AI systems experience comes from.

THE AI SKILLS I CAN DEMONSTRATE (not just claim)
1. Specification precision — reusable spec templates (intent doc, constraints doc, output contracts) rolled out to eng. Pipeline specs with explicit Pydantic contracts and approved-tag vocabularies.
2. Evaluation & quality judgment — multi-layer rubric engine, golden-dataset builder, regression detector. Bar-raiser gates on any merge touching AI behavior.
3. Multi-agent orchestration — specialized pipelines with auto-classification dispatch. Complexity-aware routing: cheap model for simple cases, expensive for hard.
4. Failure pattern recognition — guardrails chained as claim extraction → grounding → severity-weighted validation. Every rejected output logged with cause.
5. Trust & security design — policy engine with pre-execution block, prompt-injection defense, post-execution validation. Multi-level cost-budget enforcement.
6. Context architecture — adaptive token-aware truncation with priority-based section removal. Data lineage from source → model → pipeline step.
7. Cost & token economics — multi-model pricing registry, tiered routing by complexity. Per-team daily budget with graduated enforcement.

AI POSITIONING
Not competing with ML engineers on theory depth. I'm an engineering leader who gets AI into production — with evaluation pipelines, guardrails, cost economics, and multi-agent orchestration already running. The market gap is not more ML researchers; it's leaders who manage organizational complexity AND have shipped real AI infrastructure.

LEADERSHIP STYLE
Collaborative by default, directive when needed. Known for staying calm when others are distressed. Build teams that can operate without me. Hire for ownership and judgment. Protect the team from organizational noise. When I leave, the team should be stronger than when I arrived.

HARD NOS (immediate disqualifiers)
- ML research companies — exposed on theory depth
- Pure enterprise IT / legacy modernization — no AI-native architecture
- Companies "exploring how AI can help our product" — not there yet
- Founder who won't delegate technical decisions — authority must match accountability
- Engineering treated as a cost center
- Roles below VP/CTO/Head of Engineering level
- Base below $200K or total comp below $300K`;

export default function ProfilePage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [resumeList, setResumes] = useState<Resume[]>([]);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [generated, setGenerated] = useState(false);
  const toastTimer = useRef<NodeJS.Timeout | null>(null);

  // Form state
  const [fitContext, setFitContext] = useState("");
  const [showExampleDrawer, setShowExampleDrawer] = useState(false);
  // Glow the "See an example" link until it's clicked once (persisted in localStorage).
  // Start true to avoid an SSR/hydration flash; read real value in useEffect.
  const [exampleLinkGlows, setExampleLinkGlows] = useState(true);
  useEffect(() => {
    try {
      if (localStorage.getItem("fit_context_example_seen") === "1") {
        setExampleLinkGlows(false);
      }
    } catch { /* SSR / private-mode safety */ }
  }, []);
  const [tracks, setTracks] = useState<TrackForm[]>([]);
  const [filters, setFilters] = useState<FiltersForm>(defaultFilters());
  const [llmModel, setLlmModel] = useState("gemini-2.0-flash");
  const [apiKey, setApiKey] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [substackSid, setSubstackSid] = useState("");
  const [awwNodeId, setAwwNodeId] = useState("");
  const [useAwwSlice, setUseAwwSlice] = useState(true);
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
      setAwwNodeId(p.aww_node_id || "");
      setUseAwwSlice(p.use_aww_slice ?? true);
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

  // New inner — throws on error. Used by handleAnalyze.
  const saveApiKeyOrThrow = async () => {
    if (!apiKey && !llmModel && Object.keys(extraKeys).length === 0) return;
    const llm: Record<string, unknown> = { model: llmModel };
    if (apiKey) llm.api_key = apiKey;
    const nonEmpty = Object.fromEntries(
      Object.entries(extraKeys).filter(([, v]) => v.trim())
    );
    if (Object.keys(nonEmpty).length > 0) llm.provider_keys = nonEmpty;
    const updated = await profileApi.update({ llm });
    setProfile(updated);
    setHasApiKey(!!updated.llm?.has_api_key);
    setProvidersWithKeys(updated.llm?.providers_with_keys || []);
    setApiKey("");
    setExtraKeys({});
    const mainProvider = llmModel.startsWith("gemini") ? "gemini"
      : llmModel.startsWith("gpt-") || llmModel.startsWith("o1-") ? "openai"
      : llmModel.startsWith("claude-") ? "anthropic" : "unknown";
    if (apiKey) track.apiKeySaved(mainProvider);
    for (const p of Object.keys(nonEmpty)) track.apiKeySaved(p);
  };

  // Existing outer — catches for the Save button path.
  const saveApiKey = async () => {
    try {
      await saveApiKeyOrThrow();
      showToast("API key saved ✓");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save key");
    }
  };

  const handleAnalyze = async () => {
    if (resumeList.length === 0) return;
    setAnalyzing(true);
    setError("");
    track.profileAnalysisStarted(resumeList[0].id, llmModel, hasApiKey);
    if (apiKey) {
      try {
        await saveApiKeyOrThrow();
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "Failed to save API key";
        setError(msg);
        track.profileAnalysisFailed(msg);
        setAnalyzing(false);
        return;
      }
    }
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

  const handleRegenerateTracks = async () => {
    if (resumeList.length === 0) return;
    setRegenerating(true);
    setError("");
    try {
      const result = await profileApi.generate(resumeList[0].id, fitContext);
      // Intentionally only update tracks — discard result.fit_context and result.filters
      // so the user's hand-edited step 3 and filters are never overwritten.
      setTracks(jsonToTracks(result.tracks));
      setDirty(true);
      showToast("Roles regenerated ✓");
      track.profileAnalyzed(resumeList[0].id);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Regeneration failed";
      setError(msg);
    } finally {
      setRegenerating(false);
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
      payload.aww_node_id = awwNodeId;
      payload.use_aww_slice = useAwwSlice;
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
      setAwwNodeId(updated.aww_node_id || "");
      setUseAwwSlice(updated.use_aww_slice ?? true);
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

        {error && !hasProfile && !generated && (
          <div className="pb-6 pl-8">
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5">
              <p className="text-sm text-red-700">{error}</p>
              <p className="mt-1 text-xs text-red-600/70">
                If this keeps happening, double-check your API key and model selection in step 2, then try again.
              </p>
            </div>
          </div>
        )}

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
            subtitle="This is the single biggest lever on match quality. The AI reads it before scoring every job."
          >
            <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-xs text-amber-800">
                <span className="font-semibold">Most important step.</span>{" "}
                Be specific: seniority, industries, company stages, what you want to build, and hard dealbreakers.
              </p>
            </div>
            <div className="mb-2 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setShowExampleDrawer(true);
                  if (exampleLinkGlows) {
                    try { localStorage.setItem("fit_context_example_seen", "1"); } catch { /* ignore */ }
                    setExampleLinkGlows(false);
                  }
                }}
                className={`text-sm font-medium text-emerald-600 hover:text-emerald-700 cursor-pointer transition-colors inline-block ${
                  exampleLinkGlows ? "animate-attention-pulse" : ""
                }`}
              >
                See an example →
              </button>
            </div>
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
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs text-gray-500">
                Generated from your resume and step 3. Edit or regenerate as you refine your context.
              </p>
              <button
                type="button"
                onClick={handleRegenerateTracks}
                disabled={regenerating || resumeList.length === 0 || !fitContext.trim() || (!hasApiKey && !apiKey)}
                className="shrink-0 rounded-full border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-emerald-500 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
              >
                {regenerating ? "Regenerating…" : "Regenerate roles"}
              </button>
            </div>
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
            <div className="space-y-6">
              {/* Substack */}
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

              {/* AWW */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  AWW node ID{" "}
                  {awwNodeId && <span className="font-normal text-green-600">✓ set</span>}
                </label>
                <input
                  type="text"
                  value={awwNodeId}
                  onChange={(e) => { setAwwNodeId(e.target.value); setDirty(true); }}
                  placeholder="e.g. 107f0a25c6fd"
                  className={inputClass}
                />
                <p className="mt-1.5 text-xs text-gray-400">
                  Optional. If set, your AWW networking profile can be appended to your
                  scoring context.
                </p>

                {awwNodeId && (
                  <div className="mt-3 flex items-center gap-3">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={useAwwSlice}
                      onClick={() => { setUseAwwSlice((v) => !v); setDirty(true); }}
                      className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${
                        useAwwSlice ? "bg-emerald-600" : "bg-gray-200"
                      }`}
                    >
                      <span
                        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                          useAwwSlice ? "translate-x-5" : "translate-x-0"
                        }`}
                      />
                    </button>
                    <div>
                      <p className="text-sm font-medium text-gray-700">
                        {useAwwSlice ? "Appending AWW slice to scoring context" : "AWW slice disabled"}
                      </p>
                      <p className="text-xs text-gray-400">
                        {useAwwSlice
                          ? "Scorer sees: your fit context + AWW networking profile"
                          : "Scorer sees: your fit context only"}
                      </p>
                    </div>
                  </div>
                )}
              </div>
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

      <FitContextExampleDrawer
        open={showExampleDrawer}
        initialText={FIT_CONTEXT_EXAMPLE}
        onClose={() => setShowExampleDrawer(false)}
        onApply={(text) => {
          setFitContext(text);
          setDirty(true);
          setGenerated(false);
          setShowExampleDrawer(false);
        }}
      />
    </div>
  );
}
