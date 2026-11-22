import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

const Ctx = createContext<(msg: string) => void>(() => undefined);

/** One short message at a time at the bottom of the screen ("Team 7 counted"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const show = useCallback((m: string) => {
    setMsg(m);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(null), 3500);
  }, []);
  return (
    <Ctx.Provider value={show}>
      {children}
      <div className="toast" role="status" aria-live="polite">
        {msg && <p>{msg}</p>}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
