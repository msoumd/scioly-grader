/** Tiny hash router (#/scan, #/review, #/review/12) so the phone's back button works. */
import { useEffect, useState } from "react";

export type Route =
  { tab: "scan" } | { tab: "review" } | { tab: "review"; scanId: number } | { tab: "duplicates" };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "review") {
    const id = Number(parts[1]);
    return Number.isInteger(id) && id > 0 ? { tab: "review", scanId: id } : { tab: "review" };
  }
  if (parts[0] === "duplicates") return { tab: "duplicates" };
  return { tab: "scan" };
}

export function href(route: Route): string {
  if ("scanId" in route) return `#/review/${route.scanId}`;
  return `#/${route.tab}`;
}

export function go(route: Route, replace = false): void {
  if (replace) history.replaceState(null, "", href(route));
  else location.hash = href(route);
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
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
