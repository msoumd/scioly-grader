/**
 * Upload queue that survives Wi-Fi drops and page reloads.
 *
 * Every photo is saved on the device (IndexedDB) *before* it is sent, and stays there
 * until the server accepts it. Network failures, timeouts, rate limits and server errors
 * are retried with growing waits (1 s, 2 s, 4 s ... up to 30 s), and immediately when the
 * phone comes back online. A logged-out session pauses the queue until the grader logs in
 * again. Files the server refuses (wrong type, too big) are kept with the reason so the
 * grader can see what happened and dismiss them.
 */
import { ApiError, type UploadOut } from "../api/client";

export type ItemState = "waiting" | "uploading" | "paused" | "rejected";

export interface QueueItem {
  id: string;
  eventCode: string;
  filename: string;
  blob: Blob;
  createdAt: number;
  attempts: number;
  state: ItemState;
  nextTryAt: number;
  error?: string;
  progress?: number;
}

export interface QueueStore {
  all(): Promise<QueueItem[]>;
  put(item: QueueItem): Promise<void>;
  remove(id: string): Promise<void>;
}

export type Uploader = (item: QueueItem, onProgress: (f: number) => void) => Promise<UploadOut>;

export const MAX_DELAY_MS = 30_000;

/** Wait before the next try after `attempts` failures: 1 s, 2 s, 4 s ... capped at 30 s. */
export function retryDelay(attempts: number): number {
  return Math.min(MAX_DELAY_MS, 1000 * 2 ** Math.max(0, attempts - 1));
}

/** What to do after a failed upload. */
export function classify(err: unknown): "retry" | "login" | "reject" {
  if (err instanceof ApiError) {
    if (err.status === 401) return "login";
    return err.retryable ? "retry" : "reject";
  }
  return "retry"; // unknown failure: keep the photo and try again
}

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type Listener = (items: QueueItem[]) => void;
type UploadedListener = (item: QueueItem, result: UploadOut) => void;

export class UploadQueue {
  private items: QueueItem[] = [];
  private listeners = new Set<Listener>();
  private uploadedListeners = new Set<UploadedListener>();
  private running = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private loaded: Promise<void> | undefined;

  constructor(
    private readonly store: QueueStore,
    private readonly uploader: Uploader,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** Load anything left from an earlier visit and start sending it. */
  start(): Promise<void> {
    this.loaded ??= this.store.all().then((saved) => {
      // An upload interrupted by closing the app is simply tried again.
      this.items = saved
        .map((i) => (i.state === "uploading" ? { ...i, state: "waiting" as const } : i))
        .sort((a, b) => a.createdAt - b.createdAt);
      this.emit();
      void this.pump();
    });
    return this.loaded;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.snapshot());
    return () => this.listeners.delete(fn);
  }

  onUploaded(fn: UploadedListener): () => void {
    this.uploadedListeners.add(fn);
    return () => this.uploadedListeners.delete(fn);
  }

  snapshot(): QueueItem[] {
    return this.items.map((i) => ({ ...i }));
  }

  async add(eventCode: string, blob: Blob, filename: string): Promise<QueueItem> {
    await this.start();
    const item: QueueItem = {
      id: newId(),
      eventCode,
      filename,
      blob,
      createdAt: this.now(),
      attempts: 0,
      state: this.items.some((i) => i.state === "paused") ? "paused" : "waiting",
      nextTryAt: 0,
    };
    await this.store.put(item); // on the device first, so a crash can't lose it
    this.items.push(item);
    this.emit();
    void this.pump();
    return item;
  }

  /** Try everything waiting right now (e.g. the phone just came back online). */
  retryNow(): void {
    for (const i of this.items) if (i.state === "waiting") i.nextTryAt = 0;
    void this.pump();
  }

  /** After logging in again: un-pause and send. */
  resume(): void {
    for (const i of this.items) {
      if (i.state === "paused") {
        i.state = "waiting";
        i.nextTryAt = 0;
        void this.store.put(i);
      }
    }
    this.emit();
    void this.pump();
  }

  async dismiss(id: string): Promise<void> {
    const item = this.items.find((i) => i.id === id);
    if (!item || item.state === "uploading") return;
    this.items = this.items.filter((i) => i.id !== id);
    await this.store.remove(id);
    this.emit();
  }

  private emit(): void {
    const snap = this.snapshot();
    for (const fn of this.listeners) fn(snap);
  }

  private schedule(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    const waits = this.items.filter((i) => i.state === "waiting").map((i) => i.nextTryAt);
    if (!waits.length) return;
    const delay = Math.max(0, Math.min(...waits) - this.now());
    this.timer = setTimeout(() => void this.pump(), delay);
  }

  private async pump(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      for (;;) {
        const now = this.now();
        const item = this.items.find((i) => i.state === "waiting" && i.nextTryAt <= now);
        if (!item) break;
        await this.send(item);
      }
    } finally {
      this.running = false;
      this.schedule();
    }
  }

  private async send(item: QueueItem): Promise<void> {
    item.state = "uploading";
    item.progress = 0;
    this.emit();
    try {
      const result = await this.uploader(item, (f) => {
        item.progress = f;
        this.emit();
      });
      this.items = this.items.filter((i) => i.id !== item.id);
      await this.store.remove(item.id);
      this.emit();
      for (const fn of this.uploadedListeners) fn(item, result);
    } catch (err) {
      item.attempts += 1;
      item.progress = undefined;
      item.error = err instanceof Error ? err.message : String(err);
      const action = classify(err);
      if (action === "retry") {
        item.state = "waiting";
        item.nextTryAt = this.now() + retryDelay(item.attempts);
      } else if (action === "login") {
        // Everything else would fail the same way: hold all of it until logged in.
        for (const i of this.items) if (i.state === "waiting" || i === item) i.state = "paused";
      } else {
        item.state = "rejected";
      }
      await Promise.all(this.items.map((i) => this.store.put(i)));
      this.emit();
    }
  }
}

/** Keep queue items in IndexedDB (photos are stored as Blobs, which Safari supports). */
export class IdbStore implements QueueStore {
  private db: Promise<IDBDatabase> | undefined;

  constructor(
    private readonly name = "scioly-grader",
    private readonly table = "uploads",
  ) {}

  private open(): Promise<IDBDatabase> {
    this.db ??= new Promise((resolve, reject) => {
      const req = indexedDB.open(this.name, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(this.table, { keyPath: "id" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return this.db;
  }

  private async run<T>(mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest<T>) {
    const db = await this.open();
    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(this.table, mode);
      const req = op(tx.objectStore(this.table));
      tx.oncomplete = () => resolve(req.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  all(): Promise<QueueItem[]> {
    return this.run("readonly", (s) => s.getAll() as IDBRequest<QueueItem[]>);
  }

  async put(item: QueueItem): Promise<void> {
    const { progress: _progress, ...rest } = item; // progress is only for the screen
    await this.run("readwrite", (s) => s.put(rest));
  }

  async remove(id: string): Promise<void> {
    await this.run("readwrite", (s) => s.delete(id));
  }
}

export class MemoryStore implements QueueStore {
  readonly data = new Map<string, QueueItem>();

  async all(): Promise<QueueItem[]> {
    return [...this.data.values()].map((i) => ({ ...i }));
  }

  async put(item: QueueItem): Promise<void> {
    this.data.set(item.id, { ...item });
  }

  async remove(id: string): Promise<void> {
    this.data.delete(id);
  }
}
