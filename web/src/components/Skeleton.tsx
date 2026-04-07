"use client";

function Shimmer({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-lg bg-gray-200 animate-pulse ${className}`} />
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-fade-up">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="space-y-2">
          <Shimmer className="h-7 w-44" />
          <Shimmer className="h-4 w-28" />
        </div>
        <Shimmer className="h-10 w-28 rounded-full" />
      </div>
      <div className="flex gap-3">
        <Shimmer className="h-8 w-32 rounded-full" />
        <Shimmer className="h-8 w-28 rounded-full" />
      </div>
      <div className="divide-y divide-gray-200/60">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="py-3 flex items-baseline gap-4">
            <Shimmer className="h-4 w-8" />
            <div className="flex-1 space-y-2">
              <Shimmer className="h-4 w-64" />
              <Shimmer className="h-3 w-96" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ProfileSkeleton() {
  return (
    <div className="space-y-8 animate-fade-up">
      {[1, 2, 3].map((i) => (
        <div key={i} className="border-t border-gray-200/60 pt-6 space-y-4">
          <Shimmer className="h-5 w-40" />
          <Shimmer className="h-10 w-full" />
          <Shimmer className="h-10 w-full" />
        </div>
      ))}
    </div>
  );
}

export function HistorySkeleton() {
  return (
    <div className="divide-y divide-gray-200/60 animate-fade-up">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="py-4 flex items-center gap-4">
          <Shimmer className="h-4 w-20" />
          <Shimmer className="h-4 w-32" />
          <Shimmer className="h-4 w-24" />
        </div>
      ))}
    </div>
  );
}
