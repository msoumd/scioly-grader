import { useEffect, useRef, useState } from "react";

/** Full-screen image (whole page or original photo). Tap the image to zoom in or out;
 * when zoomed, drag to look around. */
export function ImageViewer({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  const [zoomed, setZoomed] = useState(false);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={alt}>
      <div className="viewer__bar">
        <span>{zoomed ? "Tap to fit" : "Tap to zoom"}</span>
        <button ref={close} type="button" className="btn btn--small" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="viewer__scroll">
        <img
          src={src}
          alt={alt}
          className={zoomed ? "viewer__img viewer__img--zoomed" : "viewer__img"}
          onClick={() => setZoomed((z) => !z)}
        />
      </div>
    </div>
  );
}
