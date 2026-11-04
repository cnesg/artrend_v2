// The institution's own image when the data has one (internal preview, loaded from its URL);
// otherwise a deterministic color composition stands in.
const PALETTE = ["#c8371f", "#1f2f4a", "#2f4a3a", "#e8d9c0", "#6b2a3a", "#d9a441", "#3c3c3c", "#8aa1b1", "#e07b39", "#f3e6cf"];

function hash(seed: string): number {
  let h = 2166136261;
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return h;
}

export function Art({
  seed,
  variant,
  className,
  src,
}: {
  seed: string;
  variant?: "stripes" | "circle" | "blocks" | "bar";
  className?: string;
  src?: string | null;
}) {
  if (src)
    return (
      <div className={`art art-img ${className || ""}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" />
      </div>
    );
  const h = hash(seed || "artrend");
  const c = (i: number) => PALETTE[(h >>> (i * 3)) % PALETTE.length];
  const kinds = ["stripes", "circle", "blocks", "bar"] as const;
  const kind = variant || kinds[h % kinds.length];
  let bg = c(0);
  let inner: React.ReactNode = null;
  if (kind === "stripes") {
    const cols = [c(1), c(2), c(3), c(0), c(4), c(5)];
    const stops = cols.map((col, i) => `${col} ${(i * 100) / cols.length}% ${((i + 1) * 100) / cols.length}%`).join(", ");
    bg = `linear-gradient(90deg, ${stops})`;
  } else if (kind === "circle") {
    inner = <span className="art-circle" style={{ background: c(2) === c(0) ? c(3) : c(2) }} />;
  } else if (kind === "blocks") {
    inner = (
      <>
        <span className="art-block a" style={{ background: c(1) === c(0) ? c(4) : c(1) }} />
        <span className="art-block b" style={{ background: c(3) === c(0) ? "#fff" : c(3) }} />
      </>
    );
  } else {
    inner = <span className="art-bar" style={{ background: c(1) === c(0) ? c(5) : c(1) }} />;
  }
  return (
    <div className={`art ${className || ""}`} style={{ background: bg }} aria-hidden>
      {inner}
    </div>
  );
}
