// Hash routes, no router library: no hash or #/meine-bewertungen (start page
// after login: the user's latest results), #/ (overview),
// #/antraege/<id>/bewertung (K1), #/antraege/<id>/verlauf (K4).
import { useEffect, useState } from "react";

export type Route =
  | { page: "mine" }
  | { page: "overview" }
  | { page: "evaluation"; id: number }
  | { page: "history"; id: number };

export function parseRoute(hash: string): Route {
  if (hash === "" || hash === "#" || /^#\/meine-bewertungen\/?$/.test(hash)) return { page: "mine" };
  const m = /^#\/antraege\/(\d+)\/(bewertung|verlauf)\/?$/.exec(hash);
  if (!m) return { page: "overview" };
  return { page: m[2] === "verlauf" ? "history" : "evaluation", id: Number(m[1]) };
}

export const hrefOf = (route: Route) =>
  route.page === "mine"
    ? "#/meine-bewertungen"
    : route.page === "overview"
      ? "#/"
      : `#/antraege/${route.id}/${route.page === "history" ? "verlauf" : "bewertung"}`;

// A page with unsaved changes (K1 draft) registers a guard; leaving it
// (other route, other user) asks first.
let leaveGuard: (() => boolean) | null = null;

export function setLeaveGuard(guard: (() => boolean) | null) {
  leaveGuard = guard;
}

export const mayLeave = () => !leaveGuard || leaveGuard();

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    let current = window.location.hash;
    const onChange = () => {
      if (window.location.hash === current) return;
      if (!mayLeave()) {
        // stay: put the old address back without another hashchange
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${current}`);
        return;
      }
      current = window.location.hash;
      setRoute(parseRoute(current));
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
