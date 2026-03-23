type AzureSourceBadgeProps = {
  label: string;
  description: string;
  tone?: "sky" | "amber" | "emerald";
};

function toneClasses(tone: AzureSourceBadgeProps["tone"]): string {
  if (tone === "amber") return "border-amber-200 bg-amber-50 text-amber-800";
  if (tone === "emerald") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-sky-200 bg-sky-50 text-sky-800";
}

export default function AzureSourceBadge({
  label,
  description,
  tone = "sky",
}: AzureSourceBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${toneClasses(tone)}`}
      title={description}
    >
      {label}
    </span>
  );
}
