export const DEFAULT_CHUNK_SECONDS = 45;
export const MIN_CHUNK_SECONDS = 10;
export const MAX_CHUNK_SECONDS = 600;

// Preserve the original 30–55 second search window for a 45 second target.
export function chunkWindow(targetSeconds: number) {
  return {
    min: targetSeconds - Math.min(15, Math.floor(targetSeconds / 3)),
    max: targetSeconds + Math.min(10, Math.floor(targetSeconds / 3)),
  };
}
