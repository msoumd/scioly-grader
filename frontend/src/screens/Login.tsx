import { useState, type FormEvent } from "react";
import { api, errorMessage, type Me } from "../api/client";
import { Mark } from "../components/Icons";
import { prefs } from "../lib/prefs";

export function Login({ onLogin }: { onLogin: (me: Me) => void }) {
  const [name, setName] = useState(prefs.graderName());
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Type your name so your scores are credited to you.");
    if (!pin) return setError("Type the tournament PIN.");
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(pin, name.trim());
      prefs.setGraderName(me.name);
      onLogin(me);
    } catch (err) {
      setError(errorMessage(err));
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="brand">
        <Mark />
        <h1>SciOly Grader</h1>
      </div>
      <form onSubmit={submit} noValidate>
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="field">
          <label htmlFor="name">Your name</label>
          <input
            id="name"
            autoComplete="name"
            autoCapitalize="words"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="pin">Tournament PIN</label>
          <input
            id="pin"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
          />
          <p className="hint">The event supervisor gives this out on the day.</p>
        </div>
        <button className="btn btn--block" type="submit" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </main>
  );
}
