/** Checking a typed free-response total before it is sent (the server checks again). */

export type Parsed = { ok: true; value: string } | { ok: false; error: string };

/** `text` as typed; `max` is the event's free_response_max (decimal string). */
export function parseFreeResponse(text: string, max: string): Parsed {
  const t = text.trim().replace(",", ".");
  if (t === "") return { ok: false, error: "Type the team's free-response total." };
  if (!/^\d+(\.\d+)?$/.test(t)) return { ok: false, error: "Use a number like 42 or 42.5." };
  const halves = Number(t) * 2;
  if (!Number.isInteger(halves))
    return { ok: false, error: "Use whole or half points (like 42.5)." };
  if (Number(t) > Number(max)) return { ok: false, error: `The most is ${trim(max)}.` };
  return { ok: true, value: trim(t) };
}

/** "42.50" -> "42.5", "40.0" -> "40". */
export function trim(n: string): string {
  return n.includes(".") ? n.replace(/0+$/, "").replace(/\.$/, "") : n.replace(/^0+(?=\d)/, "");
}

/** Keypad: digits, one ".", at most one decimal place (halves only), short numbers. */
export function keypadPress(text: string, key: string): string {
  if (key === "back") return text.slice(0, -1);
  if (key === ".") return text.includes(".") ? text : (text || "0") + ".";
  if (!/^\d$/.test(key)) return text;
  const [, dec] = text.split(".");
  if (dec !== undefined && dec.length >= 1) return text;
  if (text.replace(".", "").length >= 5) return text;
  return text === "0" ? key : text + key;
}
