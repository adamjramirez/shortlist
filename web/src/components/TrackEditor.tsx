"use client";

import { useState } from "react";
import { TrackForm, emptyTrack } from "@/lib/profile-types";
import type { Resume } from "@/lib/types";
import TagInput from "./TagInput";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

interface TrackEditorProps {
  tracks: TrackForm[];
  onChange: (tracks: TrackForm[]) => void;
  resumes: Resume[];
}

function TrackCard({
  track,
  index,
  resumes,
  onUpdate,
  onRemove,
  canRemove,
}: {
  track: TrackForm;
  index: number;
  resumes: Resume[];
  onUpdate: (patch: Partial<TrackForm>) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const [showAdvanced, setShowAdvanced] = useState(
    // Auto-open if user has already set advanced fields
    (track.target_orgs !== "" && track.target_orgs !== "any") ||
      track.min_reports > 0,
  );

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-400">
          Role {index + 1}
        </span>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="rounded-md px-2 py-1 text-xs text-gray-400 hover:bg-red-50 hover:text-red-600"
          >
            Remove
          </button>
        )}
      </div>

      <div className="space-y-4">
        {/* Title */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Role title
          </label>
          <input
            value={track.title}
            onChange={(e) => onUpdate({ title: e.target.value })}
            placeholder="e.g. Senior Backend Engineer"
            className={inputClass}
          />
        </div>

        {/* Search queries */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Search queries
          </label>
          <p className="mb-1.5 text-xs text-gray-400">
            What would you type into a job board? Add a few variations.
          </p>
          <TagInput
            tags={track.search_queries}
            onChange={(q) => onUpdate({ search_queries: q })}
            placeholder='e.g. "senior python engineer"'
          />
        </div>

        {/* Resume */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Resume for this role
          </label>
          <select
            value={track.resume}
            onChange={(e) => onUpdate({ resume: e.target.value })}
            className={inputClass}
          >
            <option value="">Use default</option>
            {resumes.map((r) => (
              <option key={r.id} value={r.filename}>
                {r.filename}
              </option>
            ))}
          </select>
        </div>

        {/* Advanced */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-400 hover:text-gray-600"
          >
            <span>{showAdvanced ? "▾" : "▸"}</span>
            Advanced options
          </button>

          {showAdvanced && (
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Target company type
                </label>
                <input
                  value={track.target_orgs}
                  onChange={(e) => onUpdate({ target_orgs: e.target.value })}
                  placeholder="any"
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-400">
                  e.g. &quot;startup&quot;, &quot;enterprise&quot;, or
                  &quot;any&quot;
                </p>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Min direct reports
                </label>
                <input
                  type="number"
                  min={0}
                  value={track.min_reports}
                  onChange={(e) =>
                    onUpdate({
                      min_reports: parseInt(e.target.value) || 0,
                    })
                  }
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-400">
                  0 = no requirement
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TrackEditor({
  tracks,
  onChange,
  resumes,
}: TrackEditorProps) {
  const update = (idx: number, patch: Partial<TrackForm>) => {
    onChange(tracks.map((t, i) => (i === idx ? { ...t, ...patch } : t)));
  };

  const remove = (idx: number) => {
    onChange(tracks.filter((_, i) => i !== idx));
  };

  const add = () => {
    onChange([...tracks, emptyTrack()]);
  };

  // Auto-add first track if empty
  if (tracks.length === 0) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center">
          <p className="mb-3 text-sm text-gray-500">
            Add a role to start searching for jobs
          </p>
          <button
            type="button"
            onClick={add}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Add your first role
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {tracks.map((track, idx) => (
        <TrackCard
          key={idx}
          track={track}
          index={idx}
          resumes={resumes}
          onUpdate={(patch) => update(idx, patch)}
          onRemove={() => remove(idx)}
          canRemove={tracks.length > 1}
        />
      ))}
      <button
        type="button"
        onClick={add}
        className="w-full rounded-xl border-2 border-dashed border-gray-200 py-3 text-sm font-medium text-gray-400 hover:border-gray-300 hover:text-gray-600"
      >
        + Add another role
      </button>
    </div>
  );
}
