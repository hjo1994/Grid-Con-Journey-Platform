import { fmtInt } from "../domain/format";
import type { StatusGroup } from "../domain/status";
import type { TechShare } from "../domain/technology";
import { Swatch } from "./small";

export function StatusWidget({ groups, total }: { groups: StatusGroup[]; total: number }) {
  const max = Math.max(1, ...groups.flatMap((g) => g.rows.map((r) => r.count)));
  return (
    <section className="box" aria-labelledby="w-status">
      <h4 id="w-status">
        Status der Anfragen <small>{total} Anfragen nach Phase und Status</small>
      </h4>
      <div className="sgrp">
        {groups.map((g) => (
          <div className="grp" key={g.label}>
            <div className="gh">
              <span>{g.label}</span>
              <b>{g.count}</b>
            </div>
            {g.rows.map((r) => (
              <div className="br" key={r.label} title={`${r.label}: ${r.count} Anfragen, ${fmtInt(r.sumMaxP)} MW`}>
                <span className="n">{r.label}</span>
                <div className="t">
                  <div className={`f ${g.outside ? "mute" : ""}`} style={{ width: `${(r.count / max) * 100}%` }} />
                </div>
                <span className="v">{r.count}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export function TechWidget({ shares, activeCount }: { shares: TechShare[]; activeCount: number }) {
  return (
    <section className="box" aria-labelledby="w-tech">
      <h4 id="w-tech">
        Aktive Leistung nach Technologie <small>{activeCount} aktive Anfragen, Anteil an MW</small>
      </h4>
      <div className="stack" role="img" aria-label="Anteil der Technologien an der aktiven Leistung">
        {shares.map((s) => (
          <div key={s.label} className={`slot-${s.slot}`} title={`${s.label}: ${fmtInt(s.sumMaxP)} MW`} style={{ width: `${s.share * 100}%` }} />
        ))}
      </div>
      <div className="lg">
        {shares.map((s) => (
          <div className="r" key={s.label}>
            <Swatch slot={s.slot} />
            <span>{s.label}</span>
            <span>{s.count}</span>
            <span>{fmtInt(s.sumMaxP)} MW</span>
          </div>
        ))}
      </div>
      <p className="note">Ohne eingestellte Anfragen. Mehrere Technologien in einer Anfrage teilen ihre Leistung gleichmäßig auf und zählen bei jeder Technologie.</p>
    </section>
  );
}
