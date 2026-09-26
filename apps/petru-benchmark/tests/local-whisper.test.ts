import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LocalWhisper } from '../server/local-whisper';
import { runOptionsSchema } from '../shared/schema';
import { HOSPITAL_CONTEXT_PROMPT } from '../shared/prompt';

const workers: LocalWhisper[] = [];
const roots: string[] = [];
afterEach(async () => {
  for (const worker of workers.splice(0)) await worker.close();
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function fixture(timeoutMs = 5000) {
  const root = await mkdtemp(join(tmpdir(), 'whisper-protocol-')); roots.push(root);
  for (const file of ['model.safetensors', 'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json']) await Bun.write(join(root, file), '{}');
  const worker = new LocalWhisper({ modelPath: root, python: Bun.which('python3')!, workerPath: join(import.meta.dir, 'fixtures/whisper_worker.py'), timeoutMs });
  workers.push(worker);
  return worker;
}

describe.skipIf(!Bun.which('python3'))('local worker process protocol', () => {
  test('keeps one process warm and sends settings without cloud provider options', async () => {
    const worker = await fixture();
    const first = await worker.transcribe('first.wav', runOptionsSchema.parse({ language: 'ro' }));
    const second = await worker.transcribe('second.wav', runOptionsSchema.parse({ language: 'auto', timestamps: true, contextPrompt: HOSPITAL_CONTEXT_PROMPT, vocabulary: 'Chișinău', providerOptions: { groq: { prompt: 'cloud only' } } }));
    expect(first.text).toBe('Chișinău. Проверка.');
    expect(second.response).toMatchObject({ pid: (first.response as { pid: number }).pid, options: { language: 'auto', temperature: 0, timestamps: true, prompt: `${HOSPITAL_CONTEXT_PROMPT}\n\nVocabulary: Chișinău.` } });
    const cleared = await worker.transcribe('cleared.wav', runOptionsSchema.parse({}));
    expect(cleared.response).toHaveProperty('options.prompt', '');
    expect(JSON.stringify(second.response)).not.toContain('cloud only');
    expect(second.cost).toBeNull();
    expect(worker.status()).toEqual({ available: true, state: 'ready', device: 'cpu', error: null });
  });

  test('crashes fail the pending chunk and a later request starts a new process', async () => {
    const worker = await fixture();
    await expect(worker.transcribe('crash.wav', runOptionsSchema.parse({}))).rejects.toThrow('fixture crash');
    expect(worker.status().state).toBe('error');
    expect((await worker.transcribe('next.wav', runOptionsSchema.parse({}))).text).toContain('Chișinău');
  });

  test('timeouts and shutdown terminate the worker and settle pending requests', async () => {
    const worker = await fixture(200);
    await expect(worker.transcribe('hang.wav', runOptionsSchema.parse({}))).rejects.toThrow('time limit');
    const pending = worker.transcribe('hang.wav', runOptionsSchema.parse({})).catch(error => error as Error);
    await worker.close();
    expect(await pending).toMatchObject({ message: 'Local Whisper stopped with the server.' });
    await expect(worker.transcribe('next.wav', runOptionsSchema.parse({}))).rejects.toThrow('closed');
  });
});
