// Types generated from openapi/openapi.json (run `npm run gen:api` after the backend changes the spec).
import type { components } from './schema';

type S = components['schemas'];
export type JobStatus = S['JobStatus'];
export type CreateJobResponse = S['CreateJobResponse'];
export type JobStatusResponse = S['JobStatusResponse'];
export type TranscriptionResult = S['TranscriptionResult'];
export type MomResult = S['MomResult'];
export type ReviewContextResponse = S['ReviewContextResponse'];
export type ApprovedMom = S['ApprovedMom'];
export type DirectoryPerson = S['DirectoryPerson'];
export type ParticipantAssignment = S['ParticipantAssignment'];
export type ParticipantAssignments = S['ParticipantAssignments'];
export type ErrorDetail = S['ErrorDetail'];
export type ErrorEnvelope = S['ErrorEnvelope'];

/** Thrown for every non-2xx response. `code`/`retryable` come from the backend ErrorEnvelope when present. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryable = false,
  ) {
    super(message);
  }
}

/** Everything the UI needs from the backend. Implemented by `live.ts` (REST) and `mock.ts` (examples). */
export interface SecureMomApi {
  /** POST /api/v1/jobs — multipart field `audio` (max 300 MiB). */
  createJob(audio: Blob, filename: string): Promise<CreateJobResponse>;
  /** GET /api/v1/jobs/{id} — poll until AWAITING_REVIEW or FAILED. */
  getJob(jobId: string): Promise<JobStatusResponse>;
  /** GET /api/v1/jobs/{id}/transcript — transcription JSON with schemaVersion 1. */
  getTranscript(jobId: string): Promise<TranscriptionResult>;
  /** GET /api/v1/jobs/{id}/mom — MoM JSON with schemaVersion 1. */
  getMom(jobId: string): Promise<MomResult>;
  /** GET /api/v1/jobs/{id}/review-context — compact portal metadata and quality. */
  getReviewContext(jobId: string): Promise<ReviewContextResponse>;
  /** POST /api/v1/jobs/{id}/retry */
  retryJob(jobId: string): Promise<unknown>;
  /** GET /health — drives the "Local server: Online" indicator. */
  health(): Promise<boolean>;
  /** Persist the final reviewed document and deliver locally when recipients remain after server filtering. */
  approveMom(jobId: string, mom: unknown, recipients: string[]): Promise<ApprovedMom>;
  getApprovedMom(jobId: string): Promise<ApprovedMom>;
  /** GET /api/v1/directory?q= — local, server-owned autocomplete data. */
  searchDirectory(query: string): Promise<DirectoryPerson[]>;
  /** PUT /api/v1/jobs/{id}/participants — persist diarized speaker names. */
  saveParticipantAssignments(jobId: string, assignments: ParticipantAssignment[]): Promise<ParticipantAssignments>;
  /**
   * NOT IN THE SPEC YET — discard the job and delete audio, transcript and draft.
   * Proposed: DELETE /api/v1/jobs/{id}
   */
  discardJob(jobId: string): Promise<void>;
}
