import { createApp } from './app';
import { MAX_UPLOAD_BYTES } from './audio';
import { LocalWhisper } from './local-whisper';
import { LlamaServer } from './llama';
import { LOCAL_MOM_MODELS } from '../shared/mom';

const localWhisper = new LocalWhisper({
  modelPath: process.env.LOCAL_WHISPER_MODEL_PATH?.trim() || '',
  python: process.env.LOCAL_WHISPER_PYTHON?.trim() || undefined,
  device: process.env.LOCAL_WHISPER_DEVICE?.trim() || 'auto',
});
// Local MoM models: llama.cpp plus one GGUF path per model, named by each model's env field.
const localMom = new LlamaServer({
  bin: process.env.LLAMA_SERVER_BIN?.trim() || Bun.which('llama-server') || '',
  paths: Object.fromEntries(LOCAL_MOM_MODELS.map(model => [model.id, process.env[model.env]?.trim() || ''])),
  contextTokens: Number(process.env.LOCAL_LLM_CONTEXT) || 32768,
});
const app = createApp({
  root: process.env.DATA_DIR || '.data', apiKey: () => process.env.OPENROUTER_API_KEY?.trim() || '', localWhisper,
  localMom, judgeConcurrency: Number(process.env.MOM_JUDGE_CONCURRENCY) || 3,
});
const server = Bun.serve({
  hostname: '127.0.0.1', port: Number(process.env.PORT || 3001),
  maxRequestBodySize: MAX_UPLOAD_BYTES + 1024 * 1024,
  idleTimeout: 255, fetch: app.fetch,
});
console.log(`Speechbench server: ${server.url}`);
let closing = false;
async function stop() {
  if (closing) return;
  closing = true;
  await server.stop(true);
  await app.close();
  process.exit(0);
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
