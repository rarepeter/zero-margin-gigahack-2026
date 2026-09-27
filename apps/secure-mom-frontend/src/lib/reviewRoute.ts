export type JobQueryName = 'review' | 'approved';
export type ReviewEntryDecision = 'wait' | 'review' | 'approved' | 'failed';

interface ReviewEntryJob {
  status: string;
  stage: string;
  artifacts: {
    momAvailable: boolean;
    reviewContextAvailable: boolean;
  };
}

/** Return a review target only when the URL is not already an approved-document link. */
export function reviewJobIdFromSearch(search: string): string | null {
  const params = new URLSearchParams(search);
  if (params.has('approved')) return null;
  const jobId = params.get('review')?.trim();
  return jobId || null;
}

/** Replace all prior query data with one encoded, path-preserving job target. */
export function jobQueryPath(href: string, name: JobQueryName, jobId: string): string {
  const url = new URL(href);
  url.search = '';
  url.searchParams.set(name, jobId);
  return `${url.pathname}${url.search}`;
}

/** Decide fresh-link navigation without treating intermediate states as review-ready. */
export function reviewEntryDecision(job: ReviewEntryJob): ReviewEntryDecision {
  if (job.status === 'COMPLETED') return 'approved';
  if (job.status === 'FAILED') return 'failed';
  if (
    job.status === 'AWAITING_REVIEW'
    && job.stage === 'review_ready'
    && job.artifacts.momAvailable
    && job.artifacts.reviewContextAvailable
  ) return 'review';
  return 'wait';
}
