import { useState, useEffect, useCallback } from 'react';
import { apiClient, isApiError } from '@/lib/apiClient';
import type {
  OddsSummaryResponse,
  TrackedMatch,
  AllMatchesResponse,
} from '@/types/odds';

export function useTrackedMatches() {
  const [matches, setMatches] = useState<TrackedMatch[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMatches = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<AllMatchesResponse>('/odds/matches');
      setMatches(res.data.matches);
    } catch (err) {
      console.error('Failed to fetch tracked matches:', err);
      setError('Could not load tracked matches. Is the backend running?');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMatches();
  }, [fetchMatches]);

  return { matches, isLoading, error, refetch: fetchMatches };
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
