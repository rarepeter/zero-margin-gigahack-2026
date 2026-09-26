import { resolve, join, extname } from 'node:path';
import { createRunSchema, type Config, type Recording } from '../shared/schema';
import { MAX_UPLOAD_BYTES, prepareAudio, prepareChunkVariant } from './audio';
import { DEFAULT_CHUNK_SECONDS } from '../shared/chunking';
import { Store } from './store';
import { Queue } from './queue';
import { fetchCatalog, redact } from './openrouter';
import { LOCAL_WHISPER_MODEL } from '../shared/models';
import { localUnavailable, type LocalTranscriber } from './local-whisper';
import { HttpError, json } from './http';
import { createMomApi } from './mom';
import { ClaudeCliJudge, type Judge } from './judge';
import type { LocalMom } from './llama';


export function createApp(options: { root: string; apiKey: () => string; fetcher?: typeof fetch; loadCatalog?: boolean; localWhisper?: LocalTranscriber; judge?: Judge; localMom?: LocalMom; judgeConcurrency?: number; momDataDir?: string }) {
  const store = new Store(resolve(options.root));
  store.recover();
  const queue = new Queue(store, options.apiKey, options.fetcher, options.localWhisper);
  const mom = createMomApi({ db: store.db, judge: options.judge ?? new ClaudeCliJudge(), local: options.localMom, apiKey: options.apiKey, fetcher: options.fetcher, judgeConcurrency: options.judgeConcurrency, dataDir: options.momDataDir });
  let catalog: Config['catalog'] = { checkedAt: null, ids: null, error: null };
  if (options.loadCatalog !== false) void fetchCatalog(options.fetcher).then(value => { catalog = value; });
  let uploading = false;

  async function handle(req: Request): Promise<Response> {
    const url = new URL(req.url);
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) throw new HttpError(403, 'Use the localhost app URL.');
    const origin = req.headers.get('origin');
    if (origin) {
      const originUrl = new URL(origin);
      if (!['localhost', '127.0.0.1'].includes(originUrl.hostname) || ![url.port, '5173', process.env.PORT || '3001'].includes(originUrl.port)) throw new HttpError(403, 'Request origin is not allowed.');
    }
    const path = url.pathname;
    if (path === '/api/config' && req.method === 'GET') return json({ localWhisper: options.localWhisper?.status() ?? localUnavailable, keyConfigured: Boolean(options.apiKey()), ffmpegAvailable: Boolean(Bun.which('ffmpeg') && Bun.which('ffprobe')), maxUploadMB: MAX_UPLOAD_BYTES / 1024 / 1024, catalog } satisfies Config);
    if (path === '/api/catalog/refresh' && req.method === 'POST') { catalog = await fetchCatalog(options.fetcher); return json(catalog); }
    if (path === '/api/recordings' && req.method === 'GET') return json(store.recordings());
    if (path === '/api/recordings' && req.method === 'POST') {
      if (!Bun.which('ffmpeg') || !Bun.which('ffprobe')) throw new HttpError(503, 'Install FFmpeg first: brew install ffmpeg');
      if (uploading) throw new HttpError(409, 'Another recording is being prepared. Wait for it to finish.');
      if (Number(req.headers.get('content-length')) > MAX_UPLOAD_BYTES + 1024 * 1024) throw new HttpError(413, 'The upload limit is 250 MB.');
      uploading = true;
      try {
        const form = await req.formData();
        const file = form.get('audio');
        if (!(file instanceof File)) throw new HttpError(400, 'Attach an audio file.');
        const id = crypto.randomUUID();
        const prepared = await prepareAudio(file, store.root, id);
        const recording: Recording = { id, name: file.name, bytes: file.size, duration: prepared.duration, createdAt: new Date().toISOString(), chunkCount: prepared.chunks.length, sha256: prepared.sha256 };
        store.addRecording(recording, prepared.chunks, prepared.original);
        return json(recording, 201);
      } catch (error) { throw new HttpError(error instanceof HttpError ? error.status : 400, error instanceof Error ? error.message : 'Could not read this recording.'); }
      finally { uploading = false; }
    }
    const audioMatch = path.match(/^\/api\/recordings\/([\w-]+)\/audio$/);
    if (audioMatch && req.method === 'GET') {
      const audio = store.recording(audioMatch[1]);
      if (!audio) throw new HttpError(404, 'Recording not found.');
      const types: Record<string, string> = { '.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.flac': 'audio/flac', '.ogg': 'audio/ogg', '.webm': 'audio/webm', '.aac': 'audio/aac' };
      return new Response(Bun.file(audio.original), { headers: { 'Content-Type': types[extname(audio.recording.name).toLowerCase()] || 'application/octet-stream', 'Cache-Control': 'no-store' } });
    }
    if (path === '/api/runs' && req.method === 'GET') return json(store.runs());
    if (path === '/api/runs' && req.method === 'POST') {
      if (!req.headers.get('content-type')?.includes('application/json')) throw new HttpError(415, 'Send JSON.');
      const parsed = createRunSchema.safeParse(await req.json());
      if (!parsed.success) throw new HttpError(400, parsed.error.issues.map(i => i.message).join('; '));
      const input = parsed.data;
      const hostedModels = input.models.filter(id => id !== LOCAL_WHISPER_MODEL.id);
      if (hostedModels.length && !options.apiKey()) throw new HttpError(503, 'Add OPENROUTER_API_KEY to .env and restart the server to use hosted models.');
      if (input.models.includes(LOCAL_WHISPER_MODEL.id)) {
        const status = options.localWhisper?.status() ?? localUnavailable;
        if (!status.available) throw new HttpError(503, status.error || 'Local Whisper is unavailable.');
      }
      const recording = store.recording(input.audioId);
      if (!recording) throw new HttpError(404, 'Recording not found.');
      if (catalog.ids && hostedModels.some(id => !catalog.ids!.includes(id))) throw new HttpError(400, 'A selected model is absent from the current OpenRouter catalog. Refresh the catalog and selection.');
      const sanitized = createRunSchema.parse(redact(input, options.apiKey()));
      const chunks = sanitized.options.chunkSeconds === DEFAULT_CHUNK_SECONDS
        ? recording.chunks
        : await prepareChunkVariant(recording.original, recording.recording.duration, sanitized.options.chunkSeconds);
      const run = store.createRun(sanitized.audioId, sanitized.models, sanitized.options, chunks);
      queue.enqueue(run);
      return json(run, 201);
    }
    const runMatch = path.match(/^\/api\/runs\/([\w-]+)(\/export)?$/);
    if (runMatch && req.method === 'GET') {
      const run = store.run(runMatch[1]);
      if (!run) throw new HttpError(404, 'Run not found.');
      if (runMatch[2]) return new Response(JSON.stringify(run, null, 2), { headers: { 'Content-Type': 'application/json', 'Content-Disposition': `attachment; filename="speechbench-${run.id}.json"`, 'Cache-Control': 'no-store' } });
      return json(run);
    }
    if (path.startsWith('/api/mom/')) { const response = await mom.handle(req, path); if (response) return response; }
    if (path.startsWith('/api/')) throw new HttpError(404, 'Endpoint not found.');
    if (req.method !== 'GET' && req.method !== 'HEAD') throw new HttpError(405, 'Method not allowed.');
    const dist = resolve('dist');
    const target = resolve(dist, `.${decodeURIComponent(path)}`);
    if (target !== dist && !target.startsWith(`${dist}/`)) throw new HttpError(403, 'Invalid path.');
    const file = Bun.file(target);
    if (target !== dist && await file.exists()) return new Response(file);
    const index = Bun.file(join(dist, 'index.html'));
    if (await index.exists()) return new Response(index);
    return new Response('Start the frontend with bun run dev, or build it with bun run build.', { status: 404 });
  }
  return {
    store,
    fetch: async (req: Request) => {
      try { return await handle(req); }
      catch (error) {
        return json({ error: String(redact(error instanceof Error ? error.message : 'Unexpected server error.', options.apiKey())) }, error instanceof HttpError ? error.status : 500);
      }
    },
    mom: mom.store,
    close: async () => { await Promise.all([queue.close(), mom.close()]); store.close(); },
  };
}
