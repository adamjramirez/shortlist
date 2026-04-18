"use client";

import Link from "next/link";
import { Lock } from "@phosphor-icons/react";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

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

const EXTRA_PROVIDERS = [
  { provider: "gemini", label: "Gemini", url: "https://aistudio.google.com/apikey" },
  { provider: "openai", label: "OpenAI", url: "https://platform.openai.com/api-keys" },
  { provider: "anthropic", label: "Anthropic (Claude)", url: "https://console.anthropic.com/settings/keys" },
];

interface AiProviderFormProps {
  llmModel: string;
  onModelChange: (model: string) => void;
  apiKey: string;
  onApiKeyChange: (key: string) => void;
  hasApiKey: boolean;
  extraKeys: Record<string, string>;
  onExtraKeyChange: (provider: string, key: string) => void;
  providersWithKeys: string[];
}

function mainProvider(model: string): string {
  if (model.startsWith("gemini")) return "gemini";
  if (model.startsWith("gpt-") || model.startsWith("o1-")) return "openai";
  if (model.startsWith("claude-")) return "anthropic";
  return "";
}

export default function AiProviderForm({
  llmModel,
  onModelChange,
  apiKey,
  onApiKeyChange,
  hasApiKey,
  extraKeys,
  onExtraKeyChange,
  providersWithKeys,
}: AiProviderFormProps) {
  const keyLink = API_KEY_LINKS[llmModel];
  const currentProvider = mainProvider(llmModel);

  return (
    <div className="space-y-4">
      {!hasApiKey && (
        <p className="text-sm text-gray-600">
          Not sure which to pick?{" "}
          <Link href="/getting-started" className="text-emerald-600 hover:text-emerald-700">
            See our setup guide
          </Link>
          {" "} — most users choose Gemini (free).
        </p>
      )}
      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Model
        </label>
        <select
          value={llmModel}
          onChange={(e) => onModelChange(e.target.value)}
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
          onChange={(e) => onApiKeyChange(e.target.value)}
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
              className="text-emerald-600 hover:text-emerald-700"
            >
              {keyLink.label} →
            </a>
          </p>
        )}
        {/* Trust signal — plain-language explanation of how the key is handled. */}
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-gray-200/60 bg-gray-50 px-3 py-2.5">
          <Lock size={16} weight="regular" className="shrink-0 mt-0.5 text-gray-500" />
          <p className="text-xs text-gray-600 leading-relaxed">
            Your key travels over an encrypted connection, is stored encrypted
            on our servers, and is only used by our backend when we call the AI
            on your behalf. It never runs in your browser, and we never share it.
          </p>
        </div>
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
          {EXTRA_PROVIDERS
            .filter(({ provider }) => provider !== currentProvider)
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
                  onChange={(e) => onExtraKeyChange(provider, e.target.value)}
                  placeholder={
                    providersWithKeys.includes(provider)
                      ? "••••••• (leave blank to keep current)"
                      : `Paste ${label} key`
                  }
                  className={inputClass + " text-xs"}
                />
                <p className="mt-0.5 text-xs text-gray-400">
                  <a href={url} target="_blank" rel="noopener noreferrer"
                     className="text-emerald-600 hover:text-emerald-700">
                    Get a {label} key →
                  </a>
                </p>
              </div>
            ))}
        </div>
      </details>
    </div>
  );
}
