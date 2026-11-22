/** Small per-device memory (grader name, chosen event). Never fails if storage is blocked. */
const KEY = { name: "sg.graderName", event: "sg.event" } as const;

function get(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function set(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // private mode or storage blocked: just don't remember
  }
}

export const prefs = {
  graderName: () => get(KEY.name) ?? "",
  setGraderName: (v: string) => set(KEY.name, v),
  event: () => get(KEY.event),
  setEvent: (v: string | null) => set(KEY.event, v),
};
