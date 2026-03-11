// Structured types for profile editing UI.
// These map 1:1 to the backend config.py dataclasses.
// The `name` field is an internal key — never shown to the user.
// It's auto-generated from `title` on first save and preserved on round-trips.

export interface TrackForm {
  name: string; // internal dict key — auto-generated from title, preserved on round-trip
  title: string;
  search_queries: string[];
  resume: string;
  target_orgs: string;
  min_reports: number;
}

export interface FiltersForm {
  location: {
    remote: boolean;
    local_zip: string;
    max_commute_minutes: number;
    local_cities: string[];
  };
  salary: {
    min_base: number;
    currency: string;
  };
  role_type: {
    reject_explicit_ic: boolean;
  };
}

// Defaults

export function emptyTrack(): TrackForm {
  return {
    name: "",
    title: "",
    search_queries: [],
    resume: "",
    target_orgs: "any",
    min_reports: 0,
  };
}

export function defaultFilters(): FiltersForm {
  return {
    location: {
      remote: true,
      local_zip: "",
      max_commute_minutes: 30,
      local_cities: [],
    },
    salary: {
      min_base: 0,
      currency: "USD",
    },
    role_type: {
      reject_explicit_ic: true,
    },
  };
}

// Converters: structured ↔ JSON blob

export function tracksToJson(tracks: TrackForm[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const t of tracks) {
    const key = t.name || slugify(t.title);
    out[key] = {
      title: t.title,
      search_queries: t.search_queries,
      ...(t.resume ? { resume: t.resume } : {}),
      ...(t.target_orgs && t.target_orgs !== "any"
        ? { target_orgs: t.target_orgs }
        : {}),
      ...(t.min_reports > 0 ? { min_reports: t.min_reports } : {}),
    };
  }
  return out;
}

export function jsonToTracks(
  json: Record<string, unknown> | undefined
): TrackForm[] {
  if (!json || typeof json !== "object") return [];
  return Object.entries(json).map(([key, val]) => {
    const v = (val || {}) as Record<string, unknown>;
    return {
      name: key,
      title: (v.title as string) || key,
      search_queries: Array.isArray(v.search_queries)
        ? (v.search_queries as string[])
        : [],
      resume: (v.resume as string) || "",
      target_orgs: (v.target_orgs as string) || "any",
      min_reports: (v.min_reports as number) || 0,
    };
  });
}

export function filtersToJson(f: FiltersForm): Record<string, unknown> {
  return {
    location: { ...f.location },
    salary: { ...f.salary },
    role_type: { ...f.role_type },
  };
}

export function jsonToFilters(
  json: Record<string, unknown> | undefined
): FiltersForm {
  if (!json || typeof json !== "object") return defaultFilters();
  const loc = (json.location || {}) as Record<string, unknown>;
  const sal = (json.salary || {}) as Record<string, unknown>;
  const role = (json.role_type || {}) as Record<string, unknown>;
  return {
    location: {
      remote: loc.remote !== false,
      local_zip: (loc.local_zip as string) || "",
      max_commute_minutes: (loc.max_commute_minutes as number) || 30,
      local_cities: Array.isArray(loc.local_cities)
        ? (loc.local_cities as string[])
        : [],
    },
    salary: {
      min_base: (sal.min_base as number) || 0,
      currency: (sal.currency as string) || "USD",
    },
    role_type: {
      reject_explicit_ic: role.reject_explicit_ic !== false,
    },
  };
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}
