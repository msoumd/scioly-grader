import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type EventOut, type Me, type ScanOut } from "../api/client";
import { useToast } from "../components/Toast";
import { href } from "../lib/route";

type Group = { team: number; name: string | null; scans: ScanOut[] };

/** Questions where the team's sheets disagree, e.g. ["Q3: B / C"]. */
function differences(scans: ScanOut[]): string[] {
  const byQ = new Map<number, string[]>();
  scans.forEach((s, i) =>
    s.questions.forEach((q) => {
      const row = byQ.get(q.q) ?? Array(scans.length).fill("–");
      row[i] = q.marked.join("") || "–";
      byQ.set(q.q, row);
    }),
  );
  return [...byQ.entries()]
    .filter(([, v]) => new Set(v).size > 1)
    .sort(([a], [b]) => a - b)
    .map(([q, v]) => `Q${q}: ${v.join(" / ")}`);
}

export function Duplicates({
  event,
  me,
  onAuthLost,
}: {
  event: EventOut;
  me: Me;
  onAuthLost: () => void;
}) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const dupes = await api.duplicates(event.code);
      setGroups(
        await Promise.all(
          dupes.map(async (d) => ({
            team: d.team_number,
            name: d.team_name ?? null,
            scans: await Promise.all(d.scans.map((s) => api.scan(s.id))),
          })),
        ),
      );
      setError(null);
    } catch (err) {
      if ((err as { status?: number }).status === 401) onAuthLost();
      else setError(errorMessage(err));
    }
  }, [event.code, onAuthLost]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 0);
    return () => clearTimeout(t);
  }, [load]);

  async function choose(team: number, scan: ScanOut) {
    setBusy(true);
    try {
      await api.chooseCounted(event.code, team, scan.id);
      toast(`Team ${team}: sheet #${scan.id} now counts (${scan.mcq_score ?? "–"})`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const admin = me.role === "admin";
  return (
    <>
      <a className="back" href={href({ tab: "review" })}>
        ‹ Review
      </a>
      <h1 className="section-title" style={{ marginTop: 0 }}>
        Teams with more than one sheet
      </h1>
      {!admin && (
        <p className="alert alert--info">
          Only a supervisor (admin PIN) can choose which sheet counts. You can compare them here.
        </p>
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {groups?.length === 0 && (
        <p className="hint">No duplicates. Each team has at most one sheet.</p>
      )}
      {groups?.map((g) => {
        const diff = differences(g.scans);
        return (
          <section key={g.team} className="panel" aria-label={`Team ${g.team}`}>
            <h2>
              Team {g.team}
              {g.name ? `, ${g.name}` : ""}
            </h2>
            <p className="hint" style={{ marginBottom: 10 }}>
              {diff.length === 0
                ? "The sheets have the same answers."
                : `Answers differ on ${diff.length} question${diff.length > 1 ? "s" : ""}: ${diff.slice(0, 8).join(", ")}${diff.length > 8 ? "…" : ""}`}
            </p>
            <div className="dupes">
              {g.scans.map((s) => (
                <div key={s.id} className={`dupe${s.is_counted ? " dupe--counted" : ""}`}>
                  {s.warped_url && <img src={s.warped_url} alt={`Sheet #${s.id}`} loading="lazy" />}
                  <dl>
                    <dt>Sheet</dt>
                    <dd>
                      #{s.id} {s.is_counted ? "(counts now)" : ""}
                    </dd>
                    <dt>Score</dt>
                    <dd className="num">{s.mcq_score ?? "unreadable"}</dd>
                    <dt>Scanned by</dt>
                    <dd>{s.grader}</dd>
                    <dt>When</dt>
                    <dd>
                      {new Date(s.created_at).toLocaleTimeString([], {
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </dd>
                  </dl>
                  {admin && !s.is_counted && (
                    <button
                      type="button"
                      className="btn btn--small"
                      disabled={busy || s.mcq_score == null}
                      onClick={() => void choose(g.team, s)}
                    >
                      Count sheet #{s.id}
                    </button>
                  )}
                  <a className="back" href={href({ tab: "review", scanId: s.id })}>
                    Open
                  </a>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}
