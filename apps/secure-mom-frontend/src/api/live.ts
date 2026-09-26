import {
  ApiError,
  type ApprovedMom,
  type CreateJobResponse,
  type JobStatusResponse,
  type MomResult,
  type ReviewContextResponse,
  type SecureMomApi,
  type TranscriptionResult,
} from './types';

async function fail(res: Response): Promise<never> {
  let code = `HTTP_${res.status}`;
  let message = res.statusText || 'Request failed';
  let retryable = res.status >= 500;
  try {
    const body = await res.json();
    if (body?.error) ({ code, message, retryable } = body.error);
    else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ');
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(res.status, code, message, retryable);
}

async function req(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, init);
  if (!res.ok) await fail(res);
  return res;
}

const enc = encodeURIComponent;

export const liveApi: SecureMomApi = {
  async createJob(audio, filename) {
    const fd = new FormData();
    fd.append('audio', audio, filename);
    return (await req('/api/v1/jobs', { method: 'POST', body: fd })).json() as Promise<CreateJobResponse>;
  },
  async getJob(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}`)).json() as Promise<JobStatusResponse>;
  },
  async getTranscript(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/transcript`)).json() as Promise<TranscriptionResult>;
  },
  async getMom(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/mom`)).json() as Promise<MomResult>;
  },
  async getReviewContext(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/review-context`)).json() as Promise<ReviewContextResponse>;
  },
  async retryJob(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/retry`, { method: 'POST' })).json();
  },
  async health() {
    try {
      return (await fetch('/health', { cache: 'no-store' })).ok;
    } catch {
      return false;
    }
  },
  async approveMom(jobId, mom, recipients) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schemaVersion: 1, document: mom, recipients }),
    })).json() as Promise<ApprovedMom>;
  },
  async getApprovedMom(jobId) {
    return (await req(`/api/v1/jobs/${enc(jobId)}/approved-mom`)).json() as Promise<ApprovedMom>;
  },
  async discardJob(jobId) {
    // TODO(backend): endpoint not in openapi.json yet.
    await req(`/api/v1/jobs/${enc(jobId)}`, { method: 'DELETE' });
  },
};
