export default function SyncBadge({ timestamp, ageHours, stale, onRefresh }) {
  let displayTime = "";
  let isStale = stale;

  if (ageHours != null) {
    if (ageHours < 1) {
      displayTime = "Synced <1h ago";
    } else {
      displayTime = `Synced ${Math.floor(ageHours)}h ago`;
    }
  } else if (timestamp) {
    const diffHours = (new Date() - new Date(timestamp)) / (1000 * 60 * 60);
    // Determine stale if not explicitly passed
    if (stale === undefined) {
      isStale = diffHours > 24;
    }
    if (diffHours < 1) {
      displayTime = "Synced <1h ago";
    } else {
      displayTime = `Synced ${Math.floor(diffHours)}h ago`;
    }
  } else {
    displayTime = "Synced";
  }

  const isLight = document.documentElement.dataset.theme === "light";

  const colorClass = isStale
    ? (isLight
      ? "text-tertiary border-tertiary/60 bg-tertiary/10 hover:bg-tertiary/20"
      : "text-tertiary border-tertiary/30 bg-tertiary/10 hover:bg-tertiary/20")
    : (isLight
      ? "text-on-surface border-outline-variant/80 bg-surface-container hover:bg-surface-container-high hover:border-outline-variant"
      : "text-on-surface-variant border-outline-variant hover:bg-surface-container-high hover:text-on-surface");

  const Comp = onRefresh ? "button" : "div";

  return (
    <Comp
      onClick={(e) => {
        if (onRefresh) {
          e.preventDefault();
          e.stopPropagation();
          onRefresh();
        }
      }}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm border font-code text-[10px] font-bold uppercase transition-colors ${colorClass} ${onRefresh ? 'cursor-pointer' : 'cursor-default'}`}
      title={isStale ? "Data may be stale. Click to refresh." : "Click to refresh"}
    >
      <span>{displayTime}</span>
      <span className="material-symbols-outlined text-[12px]">refresh</span>
    </Comp>
  );
}
