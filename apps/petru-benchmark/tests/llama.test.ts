import { expect, test } from 'bun:test';
import { AffinityQueue } from '../server/llama';

// Local jobs for the model already in memory go first, so each variant loads once per run.
test('the local queue finishes one model before switching to the next', async () => {
  let loaded: string | null = null;
  const queue = new AffinityQueue(() => loaded);
  const order: string[] = [];
  const job = async (model: string) => {
    await queue.acquire(model);
    loaded = model;
    order.push(model);
    await Bun.sleep(1);
    if (queue.release()) loaded = null;
  };
  await Promise.all(['q4', 'q8', 'q4', 'q8', 'q4'].map(job));
  expect(order).toEqual(['q4', 'q4', 'q4', 'q8', 'q8']);
  expect(loaded).toBeNull();
});
