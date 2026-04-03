"use client";

interface SaveBarProps {
  dirty: boolean;
  saving: boolean;
  toast: string;
  error: string;
  onSave: () => void;
}

export default function SaveBar({ dirty, saving, toast, error, onSave }: SaveBarProps) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-200 bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          {dirty && (
            <>
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              <span className="text-sm text-gray-500">Unsaved changes</span>
            </>
          )}
          {toast && (
            <span className="text-sm font-medium text-green-600">{toast}</span>
          )}
          {error && (
            <span className={`text-sm ${error.toLowerCase().includes("rate limit") ? "text-amber-600" : "text-red-600"}`}>
              {error}
            </span>
          )}
        </div>
        <button
          onClick={onSave}
          disabled={!dirty || saving}
          className="rounded-full bg-gray-900 px-6 py-2 text-sm font-medium text-white transition-all hover:-translate-y-[1px] active:translate-y-0 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:translate-y-0"
        >
          {saving ? "Saving..." : "Save profile"}
        </button>
      </div>
    </div>
  );
}
