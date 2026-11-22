import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type UploadOut } from "../api/client";
import {
  IdbStore,
  MemoryStore,
  UploadQueue,
  classify,
  retryDelay,
  type QueueItem,
  type Uploader,
} from "./uploadQueue";

const OK: UploadOut = { scans: [{ id: 1, page: 1, status: "processing" }] };
const blob = () => new Blob(["jpeg"], { type: "image/jpeg" });

/** An uploader whose answers are scripted: an Error/ApiError rejects, anything else resolves. */
function scripted(...answers: (UploadOut | Error)[]): Uploader & { calls: number } {
  const fn = (async () => {
    fn.calls++;
    const a = answers.shift() ?? OK;
    if (a instanceof Error) throw a;
    return a;
  }) as Uploader & { calls: number };
  fn.calls = 0;
  return fn;
}

const offline = () => new ApiError(0, "network", "No connection");
const flush = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("retry rules", () => {
  it("backs off 1, 2, 4 ... seconds up to 30", () => {
    expect([1, 2, 3, 4, 5, 6, 10].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  });

  it("retries network and server trouble, pauses for login, gives up on bad files", () => {
    expect(classify(offline())).toBe("retry");
    expect(classify(new ApiError(503, "x", "x"))).toBe("retry");
    expect(classify(new ApiError(401, "not_logged_in", "x"))).toBe("login");
    expect(classify(new ApiError(415, "unsupported_type", "x"))).toBe("reject");
    expect(classify(new Error("weird"))).toBe("retry");
  });
});

describe("upload queue", () => {
  it("uploads and forgets an item once the server accepts it", async () => {
    const store = new MemoryStore();
    const q = new UploadQueue(store, scripted(OK));
    const uploaded = vi.fn();
    q.onUploaded(uploaded);
    await q.add("AP", blob(), "a.jpg");
    await flush();
    expect(uploaded).toHaveBeenCalledOnce();
    expect(q.snapshot()).toEqual([]);
    expect(store.data.size).toBe(0);
  });

  it("keeps the photo through a Wi-Fi drop and retries with growing waits", async () => {
    const store = new MemoryStore();
    const up = scripted(offline(), offline(), OK);
    const q = new UploadQueue(store, up);
    await q.add("AP", blob(), "a.jpg");
    await flush();
    expect(up.calls).toBe(1);
    expect(q.snapshot()[0]).toMatchObject({ state: "waiting", attempts: 1 });
    expect(store.data.size).toBe(1); // still on the device

    await vi.advanceTimersByTimeAsync(999);
    expect(up.calls).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(up.calls).toBe(2); // after 1 s
    await vi.advanceTimersByTimeAsync(1999);
    expect(up.calls).toBe(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(up.calls).toBe(3); // after 2 more s
    expect(q.snapshot()).toEqual([]);
    expect(store.data.size).toBe(0);
  });

  it("retries at once when the phone comes back online", async () => {
    const up = scripted(offline(), OK);
    const q = new UploadQueue(new MemoryStore(), up);
    await q.add("AP", blob(), "a.jpg");
    await flush();
    q.retryNow();
    await flush();
    expect(up.calls).toBe(2);
    expect(q.snapshot()).toEqual([]);
  });

  it("keeps a refused file with the reason until dismissed", async () => {
    const store = new MemoryStore();
    const q = new UploadQueue(store, scripted(new ApiError(415, "unsupported_type", "Not a photo")));
    const item = await q.add("AP", blob(), "notes.txt");
    await flush();
    expect(q.snapshot()[0]).toMatchObject({ state: "rejected", error: "Not a photo" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(q.snapshot()[0]!.state).toBe("rejected"); // not retried
    await q.dismiss(item.id);
    expect(q.snapshot()).toEqual([]);
    expect(store.data.size).toBe(0);
  });

  it("pauses everything when logged out and resumes after login", async () => {
    const up = scripted(new ApiError(401, "not_logged_in", "x"), OK, OK);
    const q = new UploadQueue(new MemoryStore(), up);
    await q.add("AP", blob(), "a.jpg");
    await flush();
    await q.add("AP", blob(), "b.jpg");
    await flush();
    expect(q.snapshot().map((i) => i.state)).toEqual(["paused", "paused"]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(up.calls).toBe(1);
    q.resume();
    await flush();
    expect(up.calls).toBe(3);
    expect(q.snapshot()).toEqual([]);
  });

  it("sends one at a time, oldest first", async () => {
    const order: string[] = [];
    const up: Uploader = async (item) => {
      order.push(item.filename);
      return OK;
    };
    const q = new UploadQueue(new MemoryStore(), up);
    await Promise.all([q.add("AP", blob(), "1.jpg"), q.add("AP", blob(), "2.jpg"), q.add("AP", blob(), "3.jpg")]);
    await flush();
    expect(order).toEqual(["1.jpg", "2.jpg", "3.jpg"]);
  });

  it("picks up photos left from an earlier visit (even mid-upload)", async () => {
    const store = new MemoryStore();
    const left: QueueItem = {
      id: "x",
      eventCode: "AP",
      filename: "left.jpg",
      blob: blob(),
      createdAt: 1,
      attempts: 2,
      state: "uploading",
      nextTryAt: 0,
    };
    await store.put(left);
    const up = scripted(OK);
    const q = new UploadQueue(store, up);
    await q.start();
    await flush();
    expect(up.calls).toBe(1);
    expect(store.data.size).toBe(0);
  });
});

describe("IndexedDB store", () => {
  it("saves, lists and removes items with their photo", async () => {
    vi.useRealTimers();
    const store = new IdbStore(`test-${Math.random()}`);
    const item: QueueItem = {
      id: "a",
      eventCode: "AP",
      filename: "a.jpg",
      blob: blob(),
      createdAt: 5,
      attempts: 0,
      state: "waiting",
      nextTryAt: 0,
      progress: 0.5,
    };
    await store.put(item);
    const [saved] = await store.all();
    expect(saved).toMatchObject({ id: "a", filename: "a.jpg", state: "waiting" });
    expect(saved!.progress).toBeUndefined();
    await store.remove("a");
    expect(await store.all()).toEqual([]);
  });
});
