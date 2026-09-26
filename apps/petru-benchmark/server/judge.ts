import { tmpdir } from 'node:os';
import { z } from 'zod';
import { JUDGE_MODEL } from '../shared/mom';

export const JUDGE_EFFORT = 'high';

// The judge used by the MoM benchmark. Tests inject a fake; the app uses the local Claude Code CLI.
export type Judge = {
  status(): { available: boolean; error: string | null };
  // Free-form Markdown, used for the judge's own reference minutes.
  write(system: string, user: string, signal: AbortSignal): Promise<JudgeOutput<string>>;
  // Structured output validated against a JSON schema, used for grading.
  grade(system: string, user: string, schema: object, signal: AbortSignal): Promise<JudgeOutput<unknown>>;
};
export type JudgeOutput<T> = { value: T; latencyMs: number; cost: number | null; raw: unknown };

const cliResult = z.object({
  is_error: z.boolean().optional(),
  result: z.string().optional(),
  structured_output: z.unknown().optional(),
  total_cost_usd: z.number().optional(),
}).passthrough();

// Runs `claude -p` with no tools, no MCP servers, no settings, and no CLAUDE.md, so only our prompts reach the model.
export class ClaudeCliJudge implements Judge {
  constructor(private bin = process.env.CLAUDE_BIN?.trim() || Bun.which('claude') || '', private timeoutMs = 20 * 60_000) {}
  status() {
    return this.bin ? { available: true, error: null } : { available: false, error: 'Claude Code CLI not found. Install it or set CLAUDE_BIN in .env.' };
  }
  async write(system: string, user: string, signal: AbortSignal) {
    const output = await this.run(system, user, [], signal);
    if (!output.result?.trim()) throw new Error('The judge returned no minutes.');
    return { ...output.meta, value: output.result.trim() };
  }
  async grade(system: string, user: string, schema: object, signal: AbortSignal) {
    const output = await this.run(system, user, ['--json-schema', JSON.stringify(schema)], signal);
    if (output.structured_output === undefined) throw new Error('The judge returned no structured grade.');
    return { ...output.meta, value: output.structured_output };
  }
  private async run(system: string, user: string, extra: string[], signal: AbortSignal) {
    if (!this.bin) throw new Error(this.status().error!);
    const started = performance.now();
    const child = Bun.spawn([
      this.bin, '-p', '--model', JUDGE_MODEL, '--effort', JUDGE_EFFORT, '--tools', '', '--strict-mcp-config',
      '--setting-sources', '', '--no-session-persistence', '--output-format', 'json', '--system-prompt', system, ...extra,
    ], { cwd: tmpdir(), stdin: new Blob([user]), stdout: 'pipe', stderr: 'pipe', signal: AbortSignal.any([signal, AbortSignal.timeout(this.timeoutMs)]) });
    const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
    let raw: unknown;
    try { raw = JSON.parse(stdout); } catch { throw new Error(`Claude CLI exited with ${code}: ${(stderr || stdout).trim().slice(0, 500) || 'no output'}`); }
    const parsed = cliResult.safeParse(raw);
    if (!parsed.success) throw new Error('Claude CLI returned an unexpected result.');
    if (parsed.data.is_error || code !== 0) throw new Error(`Claude CLI failed: ${parsed.data.result?.slice(0, 500) || stderr.trim().slice(0, 500) || `exit ${code}`}`);
    return { ...parsed.data, meta: { latencyMs: Math.round(performance.now() - started), cost: parsed.data.total_cost_usd ?? null, raw } };
  }
}
