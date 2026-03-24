function SkeletonBlock({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-2xl bg-slate-200/80 ${className}`} />;
}

export default function AzurePageSkeleton({
  titleWidth = "w-56",
  subtitleWidth = "w-96",
  statCount = 4,
  sectionCount = 2,
}: {
  titleWidth?: string;
  subtitleWidth?: string;
  statCount?: number;
  sectionCount?: number;
}) {
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <SkeletonBlock className={`h-10 ${titleWidth}`} />
        <SkeletonBlock className={`h-4 ${subtitleWidth} max-w-full`} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: statCount }).map((_, index) => (
          <div key={`azure-skeleton-stat-${index}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <SkeletonBlock className="h-3 w-28" />
            <SkeletonBlock className="mt-4 h-10 w-24" />
            <SkeletonBlock className="mt-3 h-3 w-32" />
          </div>
        ))}
      </div>

      <div className="grid gap-4">
        {Array.from({ length: sectionCount }).map((_, index) => (
          <section key={`azure-skeleton-section-${index}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-3">
                <SkeletonBlock className="h-6 w-48" />
                <SkeletonBlock className="h-4 w-[28rem] max-w-full" />
              </div>
              <SkeletonBlock className="h-8 w-36" />
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              {Array.from({ length: 3 }).map((__, cardIndex) => (
                <div key={`azure-skeleton-section-card-${index}-${cardIndex}`} className="rounded-xl bg-slate-50 p-4">
                  <SkeletonBlock className="h-3 w-24" />
                  <SkeletonBlock className="mt-3 h-5 w-40" />
                  <SkeletonBlock className="mt-3 h-3 w-full" />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
