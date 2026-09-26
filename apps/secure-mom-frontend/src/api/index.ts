import { liveApi } from './live';
import { mockApi } from './mock';
import type { SecureMomApi } from './types';

/** `mock` (default) = example data, no server. `live` = local Python REST server. Set in .env / .env.live. */
export const API_MODE: 'mock' | 'live' = import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock';
export const api: SecureMomApi = API_MODE === 'live' ? liveApi : mockApi;
export * from './types';
