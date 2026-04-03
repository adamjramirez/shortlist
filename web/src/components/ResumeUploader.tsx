"use client";

import type { Resume } from "@/lib/types";

interface ResumeUploaderProps {
  resumes: Resume[];
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDelete: (id: number) => void;
}

export default function ResumeUploader({ resumes, onUpload, onDelete }: ResumeUploaderProps) {
  return (
    <div className="space-y-3">
      {resumes.length > 0 && (
        <div className="space-y-2">
          {resumes.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-2.5"
            >
              <div className="flex items-center gap-2 text-sm">
                <svg className="h-4 w-4 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="font-medium text-gray-700">
                  {r.filename}
                </span>
                {r.track && (
                  <span className="font-mono text-xs text-gray-400">
                    {r.track}
                  </span>
                )}
                {r.resume_type === "pdf" && (
                  <span className="text-xs text-gray-400">
                    PDF — tailored resumes use a standard template
                  </span>
                )}
              </div>
              <button
                onClick={() => onDelete(r.id)}
                className="rounded-md px-2 py-1 text-xs text-gray-400 hover:bg-red-50 hover:text-red-600"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-2.5 text-sm text-gray-500 hover:border-emerald-400 hover:text-emerald-600 transition-colors">
        <span>+</span> Upload resume (.tex or .pdf)
        <input
          type="file"
          accept=".tex,.pdf"
          onChange={onUpload}
          className="hidden"
        />
      </label>
      <details className="text-xs text-gray-400 mt-1">
        <summary className="cursor-pointer hover:text-gray-600">
          LaTeX (.tex) recommended for best results
        </summary>
        <p className="mt-1 pl-4 text-gray-500 leading-relaxed">
          With a .tex resume, Shortlist can surgically edit your actual resume — reordering
          bullets and adjusting emphasis while preserving your exact formatting. With a PDF,
          we generate a new tailored resume using a standard template, which won&apos;t match your
          original design.
        </p>
      </details>
    </div>
  );
}
