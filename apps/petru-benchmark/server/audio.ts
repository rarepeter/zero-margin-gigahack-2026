import { mkdir, readFile, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { z } from 'zod';
import { chunkWindow, DEFAULT_CHUNK_SECONDS, MIN_CHUNK_SECONDS, MAX_CHUNK_SECONDS } from '../shared/chunking';

export const MAX_UPLOAD_BYTES = 250 * 1024 * 1024;
export type AudioChunk = { index: number; start: number; end: number; path: string };

async function command(args: string[]) {
  const process = Bun.spawn(args, { stdout: 'pipe', stderr: 'pipe' });
  const timeout = setTimeout(() => process.kill(), 180_000);
  try {
    const [stdout, stderr, exit] = await Promise.all([
      new Response(process.stdout).text(), new Response(process.stderr).text(), process.exited,
    ]);
    if (exit !== 0) throw new Error(`Audio conversion failed. Check that the file contains playable audio. ${stderr.slice(-350)}`);
    return { stdout, stderr };
  } finally { clearTimeout(timeout); }
}

// Keep all samples, and prefer a pause close to the requested target. Never overlap or
// heuristically delete repeated transcript words at chunk boundaries.
export function chunkBoundaries(duration: number, pauses: number[], targetSeconds = DEFAULT_CHUNK_SECONDS) {
  if (!Number.isInteger(targetSeconds) || targetSeconds < MIN_CHUNK_SECONDS || targetSeconds > MAX_CHUNK_SECONDS) throw new Error(`Chunk size must be a whole number from ${MIN_CHUNK_SECONDS} to ${MAX_CHUNK_SECONDS} seconds.`);
  const window = chunkWindow(targetSeconds);
  const boundaries = [0];
  let start = 0;
  while (duration - start > window.max) {
    const candidates = pauses.filter(p => p >= start + window.min && p <= start + window.max);
    const end = candidates.sort((a, b) => Math.abs(a - start - targetSeconds) - Math.abs(b - start - targetSeconds))[0] ?? start + targetSeconds;
    boundaries.push(end);
    start = end;
  }
  boundaries.push(duration);
  return boundaries;
}

async function splitAudio(wav: string, dir: string, duration: number, targetSeconds: number) {
  const { stderr } = await command(['ffmpeg', '-nostdin', '-hide_banner', '-i', wav, '-af', 'silencedetect=noise=-35dB:d=0.35', '-f', 'null', '-']);
  const pauses = [...stderr.matchAll(/silence_end: ([\d.]+) \| silence_duration: ([\d.]+)/g)].map(m => Number(m[1]) - Number(m[2]) / 2);
  const boundaries = chunkBoundaries(duration, pauses, targetSeconds);
  const chunks: AudioChunk[] = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i];
    const end = boundaries[i + 1];
    const path = join(dir, `chunk-${i}.wav`);
    await command(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', wav, '-ss', String(start), '-t', String(end - start), '-c:a', 'pcm_s16le', path]);
    chunks.push({ index: i, start, end, path });
  }
  return chunks;
}

// A new directory keeps earlier runs' prepared audio and boundaries immutable.
export async function prepareChunkVariant(original: string, duration: number, targetSeconds: number) {
  const dir = join(dirname(original), 'variants', crypto.randomUUID());
  await mkdir(dir, { recursive: true });
  try {
    return await splitAudio(join(dirname(original), 'normalized.wav'), dir, duration, targetSeconds);
  } catch (error) {
    await rm(dir, { recursive: true, force: true });
    throw error;
  }
}

export async function prepareAudio(file: File, root: string, id: string) {
  if (file.size === 0 || file.size > MAX_UPLOAD_BYTES) throw new Error('Choose an audio file between 1 byte and 250 MB.');
  if (!/\.(m4a|mp3|wav|flac|ogg|webm|aac)$/i.test(file.name)) throw new Error('Choose an M4A, MP3, WAV, FLAC, OGG, WebM, or AAC file.');
  const dir = join(root, 'audio', id);
  await mkdir(dir, { recursive: true });
  try {
    const original = join(dir, 'original');
    const wav = join(dir, 'normalized.wav');
    await Bun.write(original, file);
    const probe = await command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', original]);
    const duration = Number(z.object({ format: z.object({ duration: z.string() }) }).parse(JSON.parse(probe.stdout)).format.duration);
    if (!Number.isFinite(duration) || duration < 0.1 || duration > 7200) throw new Error('Choose a recording between 0.1 seconds and 2 hours.');
    await command(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', original, '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav]);
    const chunks = await splitAudio(wav, dir, duration, DEFAULT_CHUNK_SECONDS);
    const hasher = new Bun.CryptoHasher('sha256');
    hasher.update(await readFile(original));
    return { duration, chunks, sha256: hasher.digest('hex'), original };
  } catch (error) {
    await rm(dir, { recursive: true, force: true });
    throw error;
  }
}
