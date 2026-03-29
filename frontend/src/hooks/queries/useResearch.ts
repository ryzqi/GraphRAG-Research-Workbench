/**
 * Research hooks based on SWR
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { parseSseJson } from '../../lib/sse';
import { useApiMutation, useApiQuery } from '../../lib/swr';
import {
  confirmResearchPlan,
  createResearchSession,
  getResearchArtifacts,
  interruptResearchSession,
  resumeResearchSession,
  streamResearchSession,
  type ResearchPlanConfirmRequest,
  type ResearchResumeRequest,
  type ResearchSessionAccepted,
  type ResearchSessionCreateRequest,
  type ResearchSessionView,
} from '../../services/research';
import {
  buildResearchSessionView,
  isTerminalResearchStatus,
  mergeResearchEventEnvelopes,
  type ResearchArtifactRead,
  type ResearchEventEnvelope,
} from '../../types/researchEvents';

const NO_ID = '__none__';
const STREAM_RETRY_DELAY_MS = 1_000;
const ACTIVE_ARTIFACT_REFRESH_INTERVAL_MS = 2_000;

const KEYS = {
  all: ['research'] as const,
  session: (id: string | undefined) => [...KEYS.all, 'session', id ?? NO_ID] as const,
  artifacts: (id: string | undefined) => [...KEYS.all, 'artifacts', id ?? NO_ID] as const,
};

type StreamStatus = 'idle' | 'connecting' | 'active' | 'retrying' | 'failed';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function buildInitialSessionView(
  accepted: ResearchSessionAccepted,
  artifacts: ResearchArtifactRead[] = []
): ResearchSessionView {
  return buildResearchSessionView({
    accepted,
    events: [],
    artifacts,
  });
}

export function useResearchSession(
  sessionId: string | undefined,
  initialAccepted?: ResearchSessionAccepted | null
) {
  const [accepted, setAccepted] = useState<ResearchSessionAccepted | null>(initialAccepted ?? null);
  const [events, setEvents] = useState<ResearchEventEnvelope[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [streamError, setStreamError] = useState<Error | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setAccepted(null);
      setEvents([]);
      setStreamStatus('idle');
      setStreamError(null);
      return;
    }

    if (initialAccepted && initialAccepted.session_id === sessionId) {
      setAccepted(initialAccepted);
    }
  }, [initialAccepted, sessionId]);

  const artifactsQuery = useApiQuery(
    sessionId ? KEYS.artifacts(sessionId) : null,
    sessionId ? () => getResearchArtifacts(sessionId) : null,
    {
      refreshInterval: (latest) => {
        if (!accepted) {
          return 0;
        }
        const latestItems = (latest as { items?: ResearchArtifactRead[] } | undefined)?.items ?? [];
        const nextView = buildResearchSessionView({
          accepted,
          events,
          artifacts: latestItems,
        });
        return isTerminalResearchStatus(nextView.status)
          ? 0
          : ACTIVE_ARTIFACT_REFRESH_INTERVAL_MS;
      },
    }
  );

  const sessionView = useMemo(() => {
    if (!accepted || !sessionId || accepted.session_id !== sessionId) {
      return undefined;
    }
    return buildResearchSessionView({
      accepted,
      events,
      artifacts: artifactsQuery.data?.items ?? [],
    });
  }, [accepted, artifactsQuery.data?.items, events, sessionId]);

  const latestViewRef = useRef<ResearchSessionView | undefined>(sessionView);
  useEffect(() => {
    latestViewRef.current = sessionView;
  }, [sessionView]);

  useEffect(() => {
    if (!sessionId || !accepted || accepted.session_id !== sessionId) {
      return;
    }

    let active = true;
    const controller = new AbortController();

    const consumeStream = async () => {
      while (active) {
        const latestView = latestViewRef.current;
        if (latestView && isTerminalResearchStatus(latestView.status)) {
          setStreamStatus('idle');
          return;
        }

        const lastEventId = latestView?.last_event_id ?? null;
        try {
          setStreamError(null);
          setStreamStatus(lastEventId ? 'retrying' : 'connecting');

          const stream = await streamResearchSession(sessionId, {
            signal: controller.signal,
            lastEventId,
            resumeFromEventId: lastEventId,
          });
          setStreamStatus('active');

          let receivedEvent = false;
          for await (const event of stream) {
            if (!active) {
              return;
            }
            if (event.event !== 'research.event') {
              continue;
            }
            const envelope = parseSseJson<ResearchEventEnvelope>(event.data);
            receivedEvent = true;
            setEvents((prev) => mergeResearchEventEnvelopes(prev, [envelope]));
          }

          await artifactsQuery.refetch().catch(() => undefined);

          const refreshedView = latestViewRef.current;
          if (refreshedView && isTerminalResearchStatus(refreshedView.status)) {
            setStreamStatus('idle');
            return;
          }

          await sleep(receivedEvent ? 250 : STREAM_RETRY_DELAY_MS);
        } catch (caughtError) {
          if (!active || controller.signal.aborted) {
            return;
          }
          const normalized =
            caughtError instanceof Error
              ? caughtError
              : new Error('Research progress stream failed');
          setStreamError(normalized);
          setStreamStatus('failed');
          await artifactsQuery.refetch().catch(() => undefined);
          await sleep(STREAM_RETRY_DELAY_MS);
          if (active) {
            setStreamStatus('retrying');
          }
        }
      }
    };

    void consumeStream();

    return () => {
      active = false;
      controller.abort();
    };
  }, [accepted, artifactsQuery, sessionId]);

  const refetch = useCallback(async () => {
    setStreamError(null);
    await artifactsQuery.refetch();
    return latestViewRef.current;
  }, [artifactsQuery]);

  return useMemo(() => {
    const seededView =
      sessionView ??
      (accepted && sessionId && accepted.session_id === sessionId
        ? buildInitialSessionView(accepted, artifactsQuery.data?.items ?? [])
        : undefined);

    return {
      data: seededView,
      error: streamError ?? artifactsQuery.error ?? null,
      isPending:
        Boolean(sessionId) &&
        !seededView &&
        (artifactsQuery.isPending || streamStatus === 'connecting'),
      isFetching:
        artifactsQuery.isFetching ||
        streamStatus === 'connecting' ||
        streamStatus === 'active' ||
        streamStatus === 'retrying',
      streamStatus,
      refetch,
    };
  }, [
    accepted,
    artifactsQuery.data?.items,
    artifactsQuery.error,
    artifactsQuery.isFetching,
    artifactsQuery.isPending,
    refetch,
    sessionId,
    sessionView,
    streamError,
    streamStatus,
  ]);
}

export function useCreateResearchSession() {
  return useApiMutation<ResearchSessionCreateRequest, ResearchSessionAccepted>(
    createResearchSession
  );
}

export function useConfirmResearchPlan() {
  return useApiMutation<
    { sessionId: string; body: ResearchPlanConfirmRequest },
    ResearchSessionAccepted
  >(({ sessionId, body }) => confirmResearchPlan(sessionId, body));
}

export function useInterruptResearchSession() {
  return useApiMutation<{ sessionId: string; reason?: string | null }, ResearchSessionAccepted>(
    ({ sessionId, reason }) => interruptResearchSession(sessionId, { reason })
  );
}

export function useResumeResearchSession() {
  return useApiMutation<
    { sessionId: string; body: ResearchResumeRequest },
    { status: 'accepted'; resume_from_event_id: string | null; decision_count: number }
  >(({ sessionId, body }) => resumeResearchSession(sessionId, body));
}

export { KEYS as researchKeys };
