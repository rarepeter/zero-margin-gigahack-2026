export class HttpError extends Error { constructor(readonly status: number, message: string) { super(message); } }

export const json = (data: unknown, status = 200) => Response.json(data, { status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
