// Example backend used until the Python server is running (VITE_API_MODE=mock).
// Responses follow the same versioned JSON contracts as the pipeline API.
import momExample from './examples/mom.example.json';
import transcriptExample from './examples/transcript.example.json';
import { demoDirectoryMatches } from '../data/directory';
import { ApiError, type ApprovedMom, type DeliveryReceipt, type JobStatus, type JobStatusResponse, type MomResult, type ParticipantAssignments, type ReviewContextResponse, type SecureMomApi, type TranscriptionResult } from './types';

/** Simulated pipeline timing (ms from upload). Tweak to slow the demo down. */
const T_TRANSCRIBING = 400;
const T_GENERATING = 6000;
const T_READY = 10000;

interface MockJob {
  created: number;
  fail: boolean;
  filename: string;
  mediaType: string;
  sizeBytes: number;
}

const transcriptFixture = transcriptExample as unknown as TranscriptionResult;
const jobs = new Map<string, MockJob>();
const approvals = new Map<string, ApprovedMom>();

const INTERNAL_EMAIL = /^[a-z0-9][a-z0-9._%+\-]*@medpark\.test$/i;
/** Mirrors the server: keep unique internal addresses, report the rest as skipped. */
const partition = (recipients: string[]) => ({
  accepted: [...new Set(recipients.map((email) => email.trim().toLowerCase()).filter((email) => INTERNAL_EMAIL.test(email)))],
  skipped: recipients.filter((email) => !INTERNAL_EMAIL.test(email.trim())),
});
const participantAssignments = new Map<string, ParticipantAssignments>();
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const fallbackJob = (): MockJob => ({
  created: Date.now() - T_READY,
  fail: false,
  filename: 'Medpark_audio.m4a',
  mediaType: 'audio/mp4',
  sizeBytes: 733_645,
});

function statusAt(elapsed: number, fail: boolean): { status: JobStatus; stage: string } {
  if (fail && elapsed > T_GENERATING) return { status: 'FAILED', stage: 'mom_generation' };
  if (elapsed < T_TRANSCRIBING) return { status: 'QUEUED', stage: 'queued' };
  if (elapsed < T_GENERATING) return { status: 'TRANSCRIBING', stage: 'transcription' };
  if (elapsed < T_READY) return { status: 'GENERATING_MOM', stage: 'mom_generation' };
  return { status: 'AWAITING_REVIEW', stage: 'review_ready' };
}

export const mockApi: SecureMomApi = {
  async createJob(audio, filename) {
    await wait(300);
    const jobId = `job_${Math.random().toString(36).slice(2, 10)}`;
    // Upload a file whose name contains "fail" to demo the FAILED state.
    jobs.set(jobId, {
      created: Date.now(),
      fail: /fail/i.test(filename),
      filename,
      mediaType: audio.type || 'application/octet-stream',
      sizeBytes: audio.size,
    });
    return { jobId, status: 'QUEUED', stage: 'queued', createdAt: new Date().toISOString() };
  },
  async getJob(jobId) {
    const j = jobs.get(jobId) ?? fallbackJob();
    const elapsed = Date.now() - j.created;
    const approved = approvals.get(jobId);
    const { status, stage } = approved
      ? { status: 'COMPLETED' as const, stage: approved.recipients.length ? 'delivered' : 'approved' }
      : statusAt(elapsed, j.fail);
    const res: JobStatusResponse = {
      jobId,
      status,
      stage,
      createdAt: new Date(j.created).toISOString(),
      updatedAt: new Date().toISOString(),
      artifacts: {
        transcriptAvailable: elapsed >= T_GENERATING,
        momAvailable: status === 'AWAITING_REVIEW' || status === 'COMPLETED',
        reviewContextAvailable: status === 'AWAITING_REVIEW' || status === 'COMPLETED',
      },
      error: status === 'FAILED' ? { code: 'MOM_GENERATION_FAILED', message: 'Text service did not respond.', retryable: true } : null,
    };
    return res;
  },
  async getTranscript(jobId) {
    await wait(150);
    const result = { ...structuredClone(transcriptFixture), jobId };
    const saved = participantAssignments.get(jobId);
    if (saved) {
      const names = new Map(saved.assignments.map((item) => [item.speakerId, item.displayName]));
      result.speakers = result.speakers.map((speaker) => ({ ...speaker, displayName: names.get(speaker.id) ?? speaker.displayName }));
    }
    return result;
  },
  async getMom() {
    await wait(150);
    return {
      schemaVersion: 1,
      quality: { momConfidence: 0.86, confidenceScale: 'ZERO_TO_ONE' },
      document: structuredClone(momExample) as unknown as MomResult['document'],
    };
  },
  async getReviewContext(jobId) {
    await wait(100);
    const job = jobs.get(jobId) ?? fallbackJob();
    const createdAt = new Date(job.created).toISOString();
    const completedAt = new Date(Math.max(job.created + T_READY, Date.now())).toISOString();
    const response: ReviewContextResponse = {
      schemaVersion: 1,
      jobId,
      status: 'AWAITING_REVIEW',
      stage: 'review_ready',
      createdAt,
      updatedAt: completedAt,
      submittedBy: { userId: 'demo-user', displayName: 'Demo User' },
      sourceRecording: {
        originalFileName: job.filename,
        mediaType: job.mediaType,
        sizeBytes: job.sizeBytes,
        durationMs: transcriptFixture.audioMetadata.durationMs,
      },
      processing: {
        startedAt: createdAt,
        completedAt,
        elapsedMs: Math.max(T_READY, Date.now() - job.created),
        audioStageMs: T_GENERATING - T_TRANSCRIBING,
        momStageMs: T_READY - T_GENERATING,
      },
      meetingMetadata: {
        durationMs: transcriptFixture.audioMetadata.durationMs,
        speakerCount: transcriptFixture.speakers.length,
        namedSpeakerCount: transcriptFixture.speakers.filter((speaker) => speaker.displayName).length,
        languages: structuredClone(transcriptFixture.languageDetection.languages),
      },
      speakers: structuredClone(transcriptFixture.speakers),
      quality: {
        transcriptConfidence: transcriptFixture.quality.transcriptConfidence,
        momConfidence: 0.86,
        overallConfidence: null,
        confidenceScale: 'ZERO_TO_ONE',
      },
      artifacts: {
        transcript: { available: true, href: `/api/v1/jobs/${encodeURIComponent(jobId)}/transcript` },
        mom: { available: true, href: `/api/v1/jobs/${encodeURIComponent(jobId)}/mom` },
      },
    };
    const saved = participantAssignments.get(jobId);
    if (saved) {
      const names = new Map(saved.assignments.map((item) => [item.speakerId, item.displayName]));
      response.speakers = response.speakers.map((speaker) => ({ ...speaker, displayName: names.get(speaker.id) ?? speaker.displayName }));
      response.meetingMetadata.namedSpeakerCount = response.speakers.filter((speaker) => speaker.displayName).length;
    }
    return response;
  },
  async retryJob(jobId) {
    const job = jobs.get(jobId) ?? fallbackJob();
    jobs.set(jobId, { ...job, created: Date.now() - T_GENERATING, fail: false });
    return { jobId, status: 'GENERATING_MOM' };
  },
  async health() {
    return true;
  },
  async approveMom(jobId, mom, recipients) {
    await wait(400);
    const existing = approvals.get(jobId);
    if (existing) return existing;
    const { accepted, skipped } = partition(recipients);
    const approved: ApprovedMom = {
      schemaVersion: 1,
      jobId,
      approvedAt: new Date().toISOString(),
      document: structuredClone(mom) as ApprovedMom['document'],
      recipients: accepted,
      skippedRecipients: skipped,
    };
    approvals.set(jobId, approved);
    return approved;
  },
  async deliverMom(jobId, recipients) {
    await wait(400);
    if (!approvals.has(jobId)) throw new ApiError(409, 'APPROVAL_NOT_READY', 'Only an approved MoM can be sent.');
    const { accepted, skipped } = partition(recipients);
    if (!accepted.length) throw new ApiError(422, 'NO_ALLOWED_RECIPIENTS', 'None of the recipients is an allowed local address.');
    const receipt: DeliveryReceipt = {
      schemaVersion: 1,
      jobId,
      messageId: `<mock-${crypto.randomUUID()}@medpark.test>`,
      attemptedAt: new Date().toISOString(),
      recipients: accepted,
      skippedRecipients: skipped,
    };
    return receipt;
  },
  async getApprovedMom(jobId) {
    const approved = approvals.get(jobId);
    if (!approved) throw new Error('The MoM has not been approved.');
    return structuredClone(approved);
  },
  async searchDirectory(query) {
    await wait(80);
    return demoDirectoryMatches(query);
  },
  async saveParticipantAssignments(jobId, assignments) {
    await wait(150);
    const saved: ParticipantAssignments = {
      schemaVersion: 1,
      jobId,
      updatedAt: new Date().toISOString(),
      assignments: structuredClone(assignments),
    };
    participantAssignments.set(jobId, saved);
    return structuredClone(saved);
  },
  async discardJob(jobId) {
    jobs.delete(jobId);
  },
};
