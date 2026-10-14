import type { RequestStatus } from "../api/types";
import { toneOf } from "../domain/status";

export function StatusPill({ status, catalogue }: { status: string | null; catalogue: RequestStatus[] }) {
  if (!status) return <span className="dim">–</span>;
  return <span className={`pill tone-${toneOf(status, catalogue)}`}>{status}</span>;
}

export function Swatch({ slot }: { slot: number }) {
  return <i className={`sw slot-${slot}`} aria-hidden="true" />;
}

export function TechLabel({ technology, slot }: { technology: string | null; slot: number }) {
  if (!technology) return <span className="dim">–</span>;
  return (
    <span className="tech" title={technology}>
      <Swatch slot={slot} />
      <span className="t">{technology}</span>
    </span>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <p className="error" role="alert">
      {message}
    </p>
  );
}
