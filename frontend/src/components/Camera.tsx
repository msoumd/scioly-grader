/**
 * Live camera with auto-capture. About 8 times a second a downscaled frame is checked for
 * the sheet's four corner markers; when all four are seen and steady for ~0.5 s the full-
 * resolution picture is taken. After a capture it waits until the sheet changes (a corner
 * leaves the view) so one sheet is never captured twice. The shutter button always works.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { findCornerMarkers, meanBrightness } from "../lib/markers";
import { GUIDANCE_TEXT, SteadinessTracker, type Guidance } from "../lib/steadiness";

const ANALYSE_EVERY_MS = 120;
const ANALYSE_LONG_SIDE = 960;
const COOLDOWN_MS = 1000;
const JPEG_QUALITY = 0.9;

type Phase = "idle" | "starting" | "live" | "error";

function cameraError(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Camera blocked. Allow the camera in Settings > Safari > Camera, then try again. You can still upload photos below.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "No camera found. Use Upload photos below instead.";
  if (name === "NotReadableError")
    return "The camera is busy in another app. Close it and try again.";
  return "The camera couldn't start. Use Upload photos below instead.";
}

function canvasJpeg(video: HTMLVideoElement): Promise<Blob> {
  const c = document.createElement("canvas");
  c.width = video.videoWidth;
  c.height = video.videoHeight;
  c.getContext("2d")!.drawImage(video, 0, 0);
  return new Promise((resolve, reject) =>
    c.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("capture failed"))),
      "image/jpeg",
      JPEG_QUALITY,
    ),
  );
}

interface ImageCaptureLike {
  takePhoto(): Promise<Blob>;
}

/** Full-resolution still: ImageCapture.takePhoto where the browser has it, else the frame. */
async function takeStill(
  video: HTMLVideoElement,
  track: MediaStreamTrack | undefined,
): Promise<Blob> {
  const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => ImageCaptureLike })
    .ImageCapture;
  if (IC && track) {
    try {
      const photo = await Promise.race([
        new IC(track).takePhoto(),
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error("slow")), 1500)),
      ]);
      if (photo.size > 0) return photo;
    } catch {
      // fall back to the video frame
    }
  }
  return canvasJpeg(video);
}

function feedback(audio: AudioContext | null) {
  navigator.vibrate?.(40);
  if (!audio) return;
  try {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.12);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.12);
  } catch {
    // sound is a nicety
  }
}

export function Camera({ onCapture }: { onCapture: (photo: Blob) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<Guidance | "captured">("no_sheet");
  const [seen, setSeen] = useState<number[]>([]);
  const [flash, setFlash] = useState(0);
  const [count, setCount] = useState(0);
  const capturing = useRef(false);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setPhase("idle");
  }, []);

  useEffect(() => stop, [stop]);

  const capture = useCallback(async () => {
    const video = videoRef.current;
    if (!video || capturing.current || !video.videoWidth) return;
    capturing.current = true;
    try {
      const photo = await takeStill(video, streamRef.current?.getVideoTracks()[0]);
      setFlash((n) => n + 1);
      feedback(audioRef.current);
      setCount((n) => n + 1);
      onCapture(photo);
    } finally {
      capturing.current = false;
    }
  }, [onCapture]);

  // Analyse frames while live.
  useEffect(() => {
    if (phase !== "live") return;
    const video = videoRef.current!;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const tracker = new SteadinessTracker();
    let armed = true; // false after a capture until the sheet changes
    let cooldownUntil = 0;
    let last = "";
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      if (document.visibilityState === "visible" && video.videoWidth && !capturing.current) {
        const scale = Math.min(
          1,
          ANALYSE_LONG_SIDE / Math.max(video.videoWidth, video.videoHeight),
        );
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const markers = findCornerMarkers(img);
        const now = performance.now();
        const g = tracker.push({
          t: now,
          markers,
          width: img.width,
          height: img.height,
          brightness: meanBrightness(img),
        });
        if (markers.size < 4 && now > cooldownUntil) armed = true;
        const ids = [...markers.keys()].sort().join(",");
        const shown: Guidance | "captured" = !armed && g !== "too_dark" ? "captured" : g;
        if (ids + shown !== last) {
          last = ids + shown;
          setSeen([...markers.keys()]);
          setGuidance(shown);
        }
        if (g === "ready" && armed && now > cooldownUntil) {
          armed = false;
          cooldownUntil = now + COOLDOWN_MS;
          tracker.reset();
          await capture();
        }
      }
      timer = setTimeout(tick, ANALYSE_EVERY_MS);
    };
    timer = setTimeout(tick, ANALYSE_EVERY_MS);
    return () => clearTimeout(timer);
  }, [phase, capture]);

  async function start() {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setPhase("error");
      setError(
        "The camera only works over a secure (https) link. Use Upload photos below, or open the app's https address.",
      );
      return;
    }
    setPhase("starting");
    try {
      // Created on this tap: iOS only allows sound after a user gesture.
      const AC =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AC && !audioRef.current) audioRef.current = new AC();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1440 },
        },
      });
      streamRef.current = stream;
      const video = videoRef.current!;
      video.srcObject = stream;
      await video.play();
      setPhase("live");
    } catch (err) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setPhase("error");
      setError(cameraError(err));
    }
  }

  const live = phase === "live";
  const status =
    guidance === "captured" ? "Got it. Put the next sheet down." : GUIDANCE_TEXT[guidance];

  return (
    <section aria-label="Camera">
      <div className="camera">
        <video ref={videoRef} playsInline muted aria-label="Camera preview" />
        {live && (
          <>
            <div className="camera__guide" aria-hidden>
              {[0, 1, 2, 3].map((id) => (
                <div
                  key={id}
                  className={`target target--${id}${seen.includes(id) ? " target--seen" : ""}`}
                />
              ))}
            </div>
            <div
              key={flash}
              className={`camera__flash${flash ? " camera__flash--on" : ""}`}
              aria-hidden
            />
            <p className="camera__status" role="status" aria-live="polite">
              {status}
            </p>
          </>
        )}
        {!live && (
          <div className="camera__idle">
            {error ? (
              <p role="alert">{error}</p>
            ) : (
              <p>
                Hold the phone over the sheet. It takes the picture by itself when all four corners
                are in view.
              </p>
            )}
            <button type="button" className="btn" onClick={start} disabled={phase === "starting"}>
              {phase === "starting"
                ? "Starting camera…"
                : error
                  ? "Try the camera again"
                  : "Start camera"}
            </button>
          </div>
        )}
      </div>
      {live && (
        <div className="capture-bar">
          <div>
            <p className="hint" aria-live="polite">
              {count === 0 ? "No sheets captured yet" : `${count} captured this session`}
            </p>
            <button type="button" className="btn btn--quiet btn--small" onClick={stop}>
              Stop camera
            </button>
          </div>
          <button type="button" className="shutter" onClick={capture} aria-label="Take photo now" />
        </div>
      )}
    </section>
  );
}
