"use client";

interface AnalyzeButtonProps {
  canAnalyze: boolean;
  analyzing: boolean;
  hasResume: boolean;
  hasApiKey: boolean;
  onAnalyze: () => void;
}

export default function AnalyzeButton({
  canAnalyze,
  analyzing,
  hasResume,
  hasApiKey,
  onAnalyze,
}: AnalyzeButtonProps) {
  return (
    <div className="mt-6 flex flex-col items-center gap-3">
      <button
        onClick={onAnalyze}
        disabled={!canAnalyze || analyzing}
        className="w-full rounded-full bg-gray-900 px-6 py-3.5 text-sm font-semibold text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {analyzing ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
            Analyzing your resume...
          </span>
        ) : (
          "Analyze my resume"
        )}
      </button>
      {!canAnalyze && (
        <p className="text-xs text-gray-400">
          {!hasResume && !hasApiKey
            ? "Upload a resume and add your API key to get started"
            : !hasResume
              ? "Upload a resume first"
              : "Add your API key first"}
        </p>
      )}
    </div>
  );
}
