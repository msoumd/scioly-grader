import { useCallback, useEffect, useState } from "react";
import { api, type EventOut, type Me } from "./api/client";
import { ResultsIcon, ReviewIcon, ScanIcon, ScoresIcon } from "./components/Icons";
import { prefs } from "./lib/prefs";
import { queue } from "./lib/queue";
import { EventPicker } from "./screens/EventPicker";
import { Login } from "./screens/Login";
import { ScanScreen } from "./screens/ScanScreen";

type Auth = { state: "checking" } | { state: "out" } | { state: "in"; me: Me };

const TABS = [
  { id: "scan", label: "Scan", icon: <ScanIcon />, ready: true },
  { id: "review", label: "Review", icon: <ReviewIcon />, ready: false },
  { id: "scores", label: "Scores", icon: <ScoresIcon />, ready: false },
  { id: "results", label: "Results", icon: <ResultsIcon />, ready: false },
] as const;

export function App() {
  const [auth, setAuth] = useState<Auth>({ state: "checking" });
  const [event, setEvent] = useState<EventOut | null>(null);
  const [picking, setPicking] = useState(() => !prefs.event());

  useEffect(() => {
    api
      .me()
      .then((me) => setAuth({ state: "in", me }))
      .catch(() => setAuth({ state: "out" }));
  }, []);

  // Restore the event this phone was grading, if it still exists.
  useEffect(() => {
    if (auth.state !== "in" || event || picking) return;
    const saved = prefs.event();
    if (!saved) return;
    api
      .events()
      .then((all) => {
        const found = all.find((e) => e.code === saved);
        if (found) setEvent(found);
        else setPicking(true);
      })
      .catch(() => setPicking(true));
  }, [auth, event, picking]);

  const authLost = useCallback(() => setAuth({ state: "out" }), []);

  if (auth.state === "checking") return null;
  if (auth.state === "out") {
    return (
      <Login
        onLogin={(me) => {
          setAuth({ state: "in", me });
          queue.resume();
        }}
      />
    );
  }

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setAuth({ state: "out" });
  };

  if (picking || !event) {
    if (!picking) return null; // restoring the saved event
    return (
      <EventPicker
        me={auth.me}
        current={event?.code ?? prefs.event()}
        onAuthLost={authLost}
        onLogout={logout}
        onPick={(e) => {
          prefs.setEvent(e.code);
          setEvent(e);
          setPicking(false);
        }}
      />
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <button
          type="button"
          className="topbar__event"
          onClick={() => setPicking(true)}
          aria-label={`Event: ${event.name}. Change event`}
        >
          <strong>{event.name}</strong>
          <span>{auth.me.name}</span>
        </button>
        <button type="button" className="btn btn--quiet btn--small" onClick={logout}>
          Log out
        </button>
      </header>
      <main className="content">
        <ScanScreen event={event} onAuthLost={authLost} />
      </main>
      <nav className="tabbar" aria-label="Sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className="tab"
            disabled={!t.ready}
            aria-current={t.id === "scan" ? "page" : undefined}
            title={t.ready ? undefined : "Coming soon"}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
