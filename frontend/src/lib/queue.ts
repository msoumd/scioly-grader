/** The app's one upload queue, saved in IndexedDB and retried when the phone is back online. */
import { uploadScan } from "../api/client";
import { IdbStore, MemoryStore, UploadQueue, type QueueStore } from "./uploadQueue";

function store(): QueueStore {
  return typeof indexedDB !== "undefined" ? new IdbStore() : new MemoryStore();
}

export const queue = new UploadQueue(store(), (item, onProgress) =>
  uploadScan(item.eventCode, item.blob, item.filename, onProgress),
);

if (typeof window !== "undefined") {
  window.addEventListener("online", () => queue.retryNow());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") queue.retryNow();
  });
}
