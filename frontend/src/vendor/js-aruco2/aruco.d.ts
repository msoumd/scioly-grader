// Types for the parts of the vendored js-aruco2 the app uses.
export interface ArucoMarker {
  id: number;
  corners: { x: number; y: number }[];
  hammingDistance: number;
}
export declare const AR: {
  Detector: new (config?: { dictionaryName?: string; maxHammingDistance?: number }) => {
    detect(image: { width: number; height: number; data: Uint8ClampedArray }): ArucoMarker[];
  };
};
