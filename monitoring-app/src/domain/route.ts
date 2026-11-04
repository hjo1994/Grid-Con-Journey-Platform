// Hash routes, no router library: #/ (overview), #/antraege/<id>/bewertung (K1),
// #/antraege/<id>/verlauf (K4).
import { useEffect, useState } from "react";

export type Route =
  | { page: "overview" }
  | { page: "evaluation"; id: number }
  | { page: "history"; id: number };

export function parseRoute(hash: string): Route {
  const m = /^#\/antraege\/(\d+)\/(bewertung|verlauf)\/?$/.exec(hash);
  if (!m) return { page: "overview" };
  return { page: m[2] === "verlauf" ? "history" : "evaluation", id: Number(m[1]) };
}

export const hrefOf = (route: Route) =>
  route.page === "overview" ? "#/" : `#/antraege/${route.id}/${route.page === "history" ? "verlauf" : "bewertung"}`;

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
