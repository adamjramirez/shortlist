/** Reusable skeleton primitives for loading states. */

export function SkeletonLine({ className = "" }: { className?: string }) {
  return (
    <div className={`h-3 rounded bg-gray-200 animate-pulse ${className}`} />
  );
}

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-lg bg-gray-200 animate-pulse ${className}`} />
  );
}

/** Mimics a JobCard while loading. */
export function JobCardSkeleton() {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex items-center gap-3">
        <div className="h-6 w-10 rounded bg-gray-200 animate-pulse" />
        <SkeletonLine className="w-48 h-4" />
      </div>
      <div className="flex items-center gap-2">
        <SkeletonLine className="w-28" />
        <SkeletonLine className="w-20" />
        <SkeletonLine className="w-16" />
      </div>
      <div className="flex items-center gap-2">
        <SkeletonLine className="w-14" />
        <SkeletonLine className="w-32" />
      </div>
    </div>
  );
}

/** Mimics the Dashboard header + filters + job list. */
export function DashboardSkeleton() {
  return (
    <div>
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="space-y-2">
          <SkeletonLine className="w-40 h-6" />
          <SkeletonLine className="w-24" />
        </div>
        <SkeletonBlock className="h-10 w-28" />
      </div>
      <div className="mb-4 flex gap-3">
        <SkeletonBlock className="h-8 w-32" />
        <SkeletonBlock className="h-8 w-28" />
      </div>
      <div className="space-y-3">
        <JobCardSkeleton />
        <JobCardSkeleton />
        <JobCardSkeleton />
      </div>
    </div>
  );
}

/** Mimics the Profile page sections. */
export function ProfileSkeleton() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="space-y-2">
        <SkeletonLine className="w-40 h-6" />
        <SkeletonLine className="w-64" />
      </div>
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-lg border border-gray-200 bg-white p-6 space-y-3">
          <SkeletonLine className="w-36 h-4" />
          <SkeletonLine className="w-full" />
          <SkeletonBlock className="h-20 w-full" />
        </div>
      ))}
    </div>
  );
}

/** Mimics the History page run list. */
export function HistorySkeleton() {
  return (
    <div>
      <SkeletonLine className="w-32 h-6 mb-6" />
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-lg border border-gray-200 bg-white p-4 flex items-center gap-3">
            <SkeletonBlock className="h-5 w-16" />
            <SkeletonLine className="w-40" />
          </div>
        ))}
      </div>
    </div>
  );
}
