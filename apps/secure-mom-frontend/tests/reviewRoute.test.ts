import assert from 'node:assert/strict';
import test from 'node:test';

import { jobQueryPath, reviewEntryDecision, reviewJobIdFromSearch } from '../src/lib/reviewRoute.ts';

test('reviewJobIdFromSearch restores a non-empty review target', () => {
  assert.equal(reviewJobIdFromSearch('?review=job-123'), 'job-123');
  assert.equal(reviewJobIdFromSearch('?review=%20job-123%20'), 'job-123');
});

test('approved links take precedence over review links', () => {
  assert.equal(reviewJobIdFromSearch('?review=draft&approved=final'), null);
});

test('missing and empty review targets are ignored', () => {
  assert.equal(reviewJobIdFromSearch(''), null);
  assert.equal(reviewJobIdFromSearch('?review=%20%20'), null);
});

test('jobQueryPath preserves the deployment path and safely encodes the job ID', () => {
  assert.equal(
    jobQueryPath('http://127.0.0.1:3100/secure-mom/?review=old#ignored', 'approved', 'job /?&'),
    '/secure-mom/?approved=job+%2F%3F%26',
  );
});

test('jobQueryPath creates the persistent review URL used immediately after upload', () => {
  assert.equal(
    jobQueryPath('http://127.0.0.1:3100/', 'review', 'job-123'),
    '/?review=job-123',
  );
});

test('review entry opens only a durable review_ready checkpoint', () => {
  assert.equal(reviewEntryDecision({
    status: 'AWAITING_REVIEW',
    stage: 'review_ready',
    artifacts: { momAvailable: true, reviewContextAvailable: true },
  }), 'review');
  assert.equal(reviewEntryDecision({
    status: 'AWAITING_REVIEW',
    stage: 'delivery_sending',
    artifacts: { momAvailable: true, reviewContextAvailable: true },
  }), 'wait');
  assert.equal(reviewEntryDecision({
    status: 'AWAITING_REVIEW',
    stage: 'review_ready',
    artifacts: { momAvailable: false, reviewContextAvailable: true },
  }), 'wait');
});

test('review entry distinguishes processing, approved, and failed jobs', () => {
  const artifacts = { momAvailable: true, reviewContextAvailable: true };
  assert.equal(reviewEntryDecision({ status: 'GENERATING_MOM', stage: 'text_processing', artifacts }), 'wait');
  assert.equal(reviewEntryDecision({ status: 'COMPLETED', stage: 'approved', artifacts }), 'approved');
  assert.equal(reviewEntryDecision({ status: 'FAILED', stage: 'mom_generation', artifacts }), 'failed');
});
