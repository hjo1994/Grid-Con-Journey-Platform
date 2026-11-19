// Evaluation journey (demo data only): requests overview -> criteria
// timeline -> sub-criterion cockpit -> evaluation cockpit. Hash routes:
// #/ overview, #/anfragen/<id> criteria of one request.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { BY_ID, IS_DEMO, ROLES, ME } from "./data";
import { mountCriteria } from "./criteria";
import { Overview } from "./Overview";

const parse = (hash: string) => {
  const m = /^#\/anfragen\/(\d+)\/?$/.exec(hash);
  return m && BY_ID[+m[1]] ? +m[1] : null;
};
const FADE_MS = 340;

/** `signOut`: show the sign-out link (only behind the OIDC login, see AuthApp.tsx). */
export default function JourneyApp({ signOut = false }: { signOut?: boolean }) {
  const [id, setId] = useState(() => parse(window.location.hash));
  const [out, setOut] = useState(false);
  const overviewY = useRef(0);

  useEffect(() => {
    const onHash = () => {
      const next = parse(window.location.hash);
      // fade the current page out, then show the next one
      setOut(true);
      window.setTimeout(() => {
        setId(next);
        window.scrollTo(0, next === null ? overviewY.current : 0);
        requestAnimationFrame(() => requestAnimationFrame(() => setOut(false)));
      }, FADE_MS);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const open = (rid: number) => {
    overviewY.current = window.scrollY;
    window.location.hash = `#/anfragen/${rid}`;
  };
  // stable, so the criteria view is not rebuilt on every render
  const back = useCallback(() => { window.location.hash = "#/"; }, []);

  return (
    <>
      <header className="appbar">
        <div className="brand">GRID CON <span>Monitoring</span></div>
        <nav className="nav" aria-label="Ansichten">
          <a href="#/" className="on">Bewertung</a>
        </nav>
        <div className="who">
          angemeldet als {ROLES[ME].name}
          {IS_DEMO && <span className="demo">Demo-Daten</span>}
          {signOut && <a className="signout" href="/logout">Abmelden</a>}
        </div>
      </header>
      <main className={`page jpage ${out ? "out" : ""}`}>
        {id === null ? <Overview onOpen={open} /> : <Criteria key={id} id={id} onBack={back} />}
      </main>
    </>
  );
}

function Criteria({ id, onBack }: { id: number; onBack: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => mountCriteria(host.current!, id, onBack), [id, onBack]);
  return <div ref={host} />;
}
