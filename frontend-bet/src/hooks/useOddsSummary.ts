import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient, isApiError } from '@/lib/apiClient';
import { useAuth } from '@/contexts/AuthContext';
import type {
  OddsSummaryResponse,
  TrackedMatch,
  AllMatchesResponse,
} from '@/types/odds';

// Auto-retry config — kept small because the hook is for a dashboard, not
// background work. We want one re-attempt for the classic "Firebase auth
// not restored yet" race; beyond that, the user can hit Refresh.
const MAX_AUTO_RETRIES = 2;
const RETRY_BACKOFF_MS = 800;

function isAuthError(err: unknown): boolean {
  return isApiError(err) && (err.response?.status === 401 || err.response?.status === 403);
}

export function useTrackedMatches() {
  const { firebaseUser, isLoadingAuth } = useAuth();

  const [matches, setMatches] = useState<TrackedMatch[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track in a ref so the retry loop doesn't trigger re-renders. Reset to 0
  // on every manual refetch so the user always gets the full retry budget.
  const attemptRef = useRef(0);

  const fetchMatches = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);

    // The apiClient interceptor reads firebaseAuthInstance.currentUser
    // synchronously to attach the JWT. If Firebase hasn't restored the
    // user yet (initial page load after a hard refresh), the request goes
    // out without an Authorization header → backend 401 → user sees the
    // generic error and has to click Refresh. Gating the fetch on
    // firebaseUser being set eliminates that race for the common path.
    if (!firebaseUser) {
      setIsLoading(false);
      return;
    }

    while (attemptRef.current < MAX_AUTO_RETRIES) {
      attemptRef.current += 1;
      try {
        const res = await apiClient.get<AllMatchesResponse>('/odds/matches');
        setMatches(res.data.matches);
        setError(null);
        setIsLoading(false);
        return;
      } catch (err) {
        const isLastAttempt = attemptRef.current >= MAX_AUTO_RETRIES;
        const transient =
          !isApiError(err) || // network blip
          isAuthError(err) || // token wasn't fresh yet
          (err.response?.status !== undefined && err.response.status >= 500);

        // Surface non-transient errors immediately — no point retrying a 400.
        if (!transient || isLastAttempt) {
          console.error(
            `Failed to fetch tracked matches (attempt ${attemptRef.current}):`,
            err,
          );
          // Friendlier message for the auth race specifically.
          setError(
            isAuthError(err)
              ? 'Sign-in is still loading — please try Refresh.'
              : 'Could not load tracked matches. Is the backend running?',
          );
          setIsLoading(false);
          return;
        }

        // Linear backoff. Cheap, and 2 attempts is the whole budget anyway.
        await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS * attemptRef.current));
      }
    }
    setIsLoading(false);
  }, [firebaseUser]);

  // Initial fetch: kick off once Firebase Auth has settled (signed-in user
  // present) OR once isLoadingAuth flips false (anonymous user — request
  // will be unauthenticated, and the backend can choose to 401 cleanly).
  useEffect(() => {
    if (isLoadingAuth) return;
    attemptRef.current = 0;
    fetchMatches();
  }, [isLoadingAuth, firebaseUser, fetchMatches]);

  // Public refetch resets the retry budget so users can recover from a
  // genuine failure with one click.
  const refetch = useCallback(async () => {
    attemptRef.current = 0;
    await fetchMatches();
  }, [fetchMatches]);

  return { matches, isLoading: isLoading || isLoadingAuth, error, refetch };
}

export function useOddsSummary(matchId: string | null) {
  const [data, setData] = useState<OddsSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSummary = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<OddsSummaryResponse>(`/odds/history/${id}/summary`);
      setData(res.data);
    } catch (err) {
      console.error('Failed to fetch odds summary:', err);
      if (isApiError(err) && err.response?.status === 404) {
        setError('No odds history found for this match.');
      } else {
        setError('Failed to load odds history.');
      }
      setData(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (matchId) {
      fetchSummary(matchId);
    } else {
      setData(null);
      setError(null);
    }
  }, [matchId, fetchSummary]);

  const refetch = useCallback(() => {
    if (matchId) fetchSummary(matchId);
  }, [matchId, fetchSummary]);

  return { data, isLoading, error, refetch };
}
