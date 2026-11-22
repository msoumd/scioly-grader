/** Tiny inline icons (no icon font: works offline, nothing extra to download). */
type P = { title?: string };
const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const ScanIcon = ({ title }: P) => (
  <svg {...base} aria-hidden={!title} role={title ? "img" : undefined}>
    {title && <title>{title}</title>}
    <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3" />
    <circle cx="12" cy="12" r="3.5" />
  </svg>
);
export const ReviewIcon = () => (
  <svg {...base} aria-hidden>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-4.5-4.5" />
  </svg>
);
export const ScoresIcon = () => (
  <svg {...base} aria-hidden>
    <path d="M4 20h16M7 16V9M12 16V5M17 16v-4" />
  </svg>
);
export const ResultsIcon = () => (
  <svg {...base} aria-hidden>
    <path d="M8 4h8v5a4 4 0 0 1-8 0V4ZM12 13v4M8 20h8M16 6h3v1a3 3 0 0 1-3 3M8 6H5v1a3 3 0 0 0 3 3" />
  </svg>
);
export const Mark = ({ size = 44 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
    <rect width="64" height="64" rx="12" fill="#1f4e79" />
    {[
      [8, 8],
      [46, 8],
      [8, 46],
      [46, 46],
    ].map(([x, y]) => (
      <rect key={`${x}-${y}`} x={x} y={y} width="10" height="10" fill="#fff" />
    ))}
    <circle cx="32" cy="32" r="10" fill="none" stroke="#fff" strokeWidth="3" />
    <circle cx="32" cy="32" r="5.5" fill="#fff" />
  </svg>
);
