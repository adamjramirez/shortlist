"use client";

import { FiltersForm } from "@/lib/profile-types";
import { COUNTRIES, CURRENCIES } from "@/lib/constants";
import Combobox from "./Combobox";
import TagInput from "./TagInput";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

interface FiltersEditorProps {
  filters: FiltersForm;
  onChange: (filters: FiltersForm) => void;
}

export default function FiltersEditor({
  filters,
  onChange,
}: FiltersEditorProps) {
  const updateLocation = (patch: Partial<FiltersForm["location"]>) => {
    onChange({ ...filters, location: { ...filters.location, ...patch } });
  };

  const updateSalary = (patch: Partial<FiltersForm["salary"]>) => {
    onChange({ ...filters, salary: { ...filters.salary, ...patch } });
  };

  const updateRoleType = (patch: Partial<FiltersForm["role_type"]>) => {
    onChange({ ...filters, role_type: { ...filters.role_type, ...patch } });
  };

  return (
    <div className="space-y-5">
      {/* Location */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-sm font-semibold text-gray-700">Location</h3>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Country
            </label>
            <p className="mb-1.5 text-xs text-gray-400">
              LinkedIn searches will target jobs in this country
            </p>
            <Combobox
              options={COUNTRIES}
              value={filters.location.country}
              onChange={(val) => updateLocation({ country: val })}
              placeholder="Search countries…"
            />
            {(() => {
              const sel = COUNTRIES.find((c) => c.value === filters.location.country);
              return sel?.description ? (
                <p className="mt-1.5 text-xs text-gray-400">
                  Searches: {sel.description}
                </p>
              ) : null;
            })()}
          </div>

          <label className="flex items-center gap-2.5 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={filters.location.remote}
              onChange={(e) => updateLocation({ remote: e.target.checked })}
              className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
            />
            Include remote jobs
          </label>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Your ZIP code
              </label>
              <input
                value={filters.location.local_zip}
                onChange={(e) => updateLocation({ local_zip: e.target.value })}
                placeholder="e.g. 60601"
                className={inputClass}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Max commute
              </label>
              <div className="relative">
                <input
                  type="number"
                  min={0}
                  step={5}
                  value={filters.location.max_commute_minutes}
                  onChange={(e) =>
                    updateLocation({
                      max_commute_minutes: parseInt(e.target.value) || 0,
                    })
                  }
                  className={inputClass}
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                  min
                </span>
              </div>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Nearby cities
            </label>
            <p className="mb-1.5 text-xs text-gray-400">
              We&apos;ll match jobs posted in these cities
            </p>
            <TagInput
              tags={filters.location.local_cities}
              onChange={(cities) => updateLocation({ local_cities: cities })}
              placeholder="e.g. Chicago, Evanston"
            />
          </div>
        </div>
      </div>

      {/* Compensation */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-sm font-semibold text-gray-700">
          Compensation
        </h3>
        <div className="space-y-1">
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Minimum base salary
          </label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-gray-400">
                {CURRENCIES.find((c) => c.value === filters.salary.currency)?.symbol ?? "$"}
              </span>
              <input
                type="number"
                min={0}
                step={5000}
                value={filters.salary.min_base || ""}
                onChange={(e) =>
                  updateSalary({ min_base: parseInt(e.target.value) || 0 })
                }
                placeholder="0"
                className={`pl-7 ${inputClass}`}
              />
            </div>
            <select
              value={filters.salary.currency}
              onChange={(e) => updateSalary({ currency: e.target.value })}
              className="w-24 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {CURRENCIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-gray-400">
            Jobs below this are automatically filtered out
          </p>
        </div>
      </div>

      {/* Role preferences */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-sm font-semibold text-gray-700">
          Role preferences
        </h3>
        <label className="flex items-start gap-2.5 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={filters.role_type.reject_explicit_ic}
            onChange={(e) =>
              updateRoleType({ reject_explicit_ic: e.target.checked })
            }
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
          />
          <div>
            <span>Skip roles explicitly labeled as IC-only</span>
            <p className="mt-0.5 text-xs text-gray-400">
              e.g. &quot;Individual Contributor — no path to management&quot;
            </p>
          </div>
        </label>
      </div>
    </div>
  );
}
