import { useCallback, useEffect, useState } from "react";
import { api, type EventOut, type Me } from "./api/client";
import { ResultsIcon, ReviewIcon, ScanIcon, ScoresIcon } from "./components/Icons";
import { prefs } from "./lib/prefs";
import { queue } from "./lib/queue";
import { EventPicker } from "./screens/EventPicker";
import { Login } from "./screens/Login";
import { Duplicates } from "./screens/Duplicates";
import { ReviewQueue } from "./screens/ReviewQueue";
import { ReviewScan } from "./screens/ReviewScan";
import { ScanScreen } from "./screens/ScanScreen";
import { Results } from "./screens/Results";
import { ScoreEntry, ScoresList } from "./screens/Scores";
import { Setup } from "./screens/Setup";
import { ToastProvider } from "./components/Toast";
import { go, useRoute, type Route } from "./lib/route";

type Auth = { state: "checking" } | { state: "out" } | { state: "in"; me: Me };

const TABS = [
  { id: "scan", label: "Scan", icon: <ScanIcon />, ready: true },
  { id: "review", label: "Review", icon: <ReviewIcon />, ready: true },
  { id: "scores", label: "Scores", icon: <ScoresIcon />, ready: true },
  { id: "results", label: "Results", icon: <ResultsIcon />, ready: true },
] as const;

/** How many sheets wait for review (for the tab badge), checked every few seconds. */
function useReviewCount(eventCode: string | undefined): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!eventCode) return;
    const load = () =>
      document.visibilityState === "visible" &&
      api
        .scans(eventCode, "needs_review")
        .then((l) => setN(l.length))
        .catch(() => undefined);
    const first = setTimeout(load, 0);
    const id = setInterval(load, 5000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [eventCode]);
  return n;
}

function tabOf(route: Route): string {
  return route.tab === "duplicates" ? "review" : route.tab;
}

export function App() {
  return (
    <ToastProvider>
      <Main />
    </ToastProvider>
  );
}

function Main() {
  const route = useRoute();
  const [auth, setAuth] = useState<Auth>({ state: "checking" });
  const [event, setEvent] = useState<EventOut | null>(null);
  const [picking, setPicking] = useState(() => !prefs.event());
  const [eventsVersion, setEventsVersion] = useState(0);

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
  const reviewCount = useReviewCount(auth.state === "in" ? event?.code : undefined);

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

  if (route.tab === "setup") {
    return <Setup me={auth.me} onEventsChanged={() => setEventsVersion((v) => v + 1)} />;
  }

  if (picking || !event) {
    if (!picking) return null; // restoring the saved event
    return (
      <EventPicker
        key={eventsVersion}
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
        {route.tab === "scan" && <ScanScreen event={event} onAuthLost={authLost} />}
        {route.tab === "review" && !("scanId" in route) && (
          <ReviewQueue event={event} onAuthLost={authLost} />
        )}
        {"scanId" in route && (
          <ReviewScan scanId={route.scanId} event={event} me={auth.me} onAuthLost={authLost} />
        )}
        {route.tab === "scores" && !("team" in route) && (
          <ScoresList event={event} onAuthLost={authLost} />
        )}
        {"team" in route && (
          <ScoreEntry key={route.team} event={event} team={route.team} onAuthLost={authLost} />
        )}
        {route.tab === "results" && <Results event={event} me={auth.me} onAuthLost={authLost} />}
        {route.tab === "duplicates" && (
          <Duplicates event={event} me={auth.me} onAuthLost={authLost} />
        )}
      </main>
      <nav className="tabbar" aria-label="Sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className="tab"
            disabled={!t.ready}
            aria-current={t.id === tabOf(route) ? "page" : undefined}
            title={t.ready ? undefined : "Coming soon"}
            onClick={() => {
              go({ tab: t.id } as Route);
            }}
          >
            {t.icon}
            {t.label}
            {t.id === "review" && reviewCount > 0 && (
              <span className="tab__badge" aria-label={`${reviewCount} to review`}>
                {reviewCount}
              </span>
            )}
          </button>
        ))}
      </nav>
    </div>
  );
}
