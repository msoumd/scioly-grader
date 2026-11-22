/** Small caches for data that rarely changes during a session, plus scan preloading. */
import { api, type EventDetail, type ScanOut } from "../api/client";

const events = new Map<string, Promise<EventDetail>>();
let teams: Promise<Map<number, string>> | undefined;
const scans = new Map<number, Promise<ScanOut>>();

export function eventDetail(code: string): Promise<EventDetail> {
  let p = events.get(code);
  if (!p) {
    p = api.event(code);
    p.catch(() => events.delete(code));
    events.set(code, p);
  }
  return p;
}

export function teamNames(): Promise<Map<number, string>> {
  teams ??= api.teams().then((list) => new Map(list.map((t) => [t.team_number, t.name])));
  teams.catch(() => (teams = undefined));
  return teams;
}

/** Fetch a scan and its images ahead of time so the next review opens instantly. */
export function preloadScan(id: number): void {
  if (scans.has(id)) return;
  const p = api.scan(id);
  scans.set(id, p);
  p.then((s) => {
    for (const url of [s.team_crop_url, ...s.questions.map((q) => q.crop_url)]) {
      if (url) new Image().src = url;
    }
  }).catch(() => scans.delete(id));
}

/** A preloaded scan if there is one (used once), otherwise a fresh fetch. */
export function takeScan(id: number): Promise<ScanOut> {
  const p = scans.get(id);
  scans.delete(id);
  return p ?? api.scan(id);
}
