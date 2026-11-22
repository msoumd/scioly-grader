/** Tiny hash router (#/scan, #/review/12, #/scores/7 ...) so the phone's back button works. */
import { useEffect, useState } from "react";

export type Route =
  | { tab: "scan" }
  | { tab: "review" }
  | { tab: "review"; scanId: number }
  | { tab: "duplicates" }
  | { tab: "scores" }
  | { tab: "scores"; team: number }
  | { tab: "results" }
  | { tab: "setup" };

const id = (s: string | undefined) => {
  const n = Number(s);
  return Number.isInteger(n) && n >= 0 && s !== "" ? n : null;
};

export function parseRoute(hash: string): Route {
  const [page, arg] = hash.replace(/^#\/?/, "").split("/");
  switch (page) {
    case "review": {
      const n = id(arg);
      return n && n > 0 ? { tab: "review", scanId: n } : { tab: "review" };
    }
    case "scores": {
      const n = id(arg);
      return n !== null ? { tab: "scores", team: n } : { tab: "scores" };
    }
    case "duplicates":
    case "results":
    case "setup":
      return { tab: page };
    default:
      return { tab: "scan" };
  }
}

export function href(route: Route): string {
  if ("scanId" in route) return `#/review/${route.scanId}`;
  if ("team" in route) return `#/scores/${route.team}`;
  return `#/${route.tab}`;
}

export function go(route: Route, replace = false): void {
  if (replace) {
    history.replaceState(null, "", href(route));
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else location.hash = href(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
