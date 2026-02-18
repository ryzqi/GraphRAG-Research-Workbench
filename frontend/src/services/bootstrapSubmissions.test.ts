import { describe, expect, it } from 'vitest';

import {
  isBootstrapSubmissionTerminal,
  shouldPollBootstrapSubmission,
  type BootstrapSubmissionStatus,
} from '../hooks/queries/useBootstrapSubmissions';

const TERMINAL_STATUSES: BootstrapSubmissionStatus[] = ['completed', 'failed'];
const RUNNING_STATUSES: BootstrapSubmissionStatus[] = ['queued_upload', 'queued', 'running'];

describe('bootstrap submission polling', () => {
  it('marks completed and failed as terminal', () => {
    for (const status of TERMINAL_STATUSES) {
      expect(isBootstrapSubmissionTerminal(status)).toBe(true);
    }
  });

  it('marks queued_upload, queued and running as non-terminal', () => {
    for (const status of RUNNING_STATUSES) {
      expect(isBootstrapSubmissionTerminal(status)).toBe(false);
    }
  });

  it('polls only while non-terminal status is present', () => {
    expect(shouldPollBootstrapSubmission({ status: 'queued_upload' })).toBe(true);
    expect(shouldPollBootstrapSubmission({ status: 'queued' })).toBe(true);
    expect(shouldPollBootstrapSubmission({ status: 'running' })).toBe(true);
    expect(shouldPollBootstrapSubmission({ status: 'completed' })).toBe(false);
    expect(shouldPollBootstrapSubmission({ status: 'failed' })).toBe(false);
    expect(shouldPollBootstrapSubmission(undefined)).toBe(false);
  });
});
