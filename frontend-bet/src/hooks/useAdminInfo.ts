import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient, isApiError } from '@/lib/apiClient';
import type { AdminInfoResponse } from '@/types/admin';

// Auto-refresh cadence for the admin dashboard. 30s is fast enough to spot a
// runaway tracker quickly without burning the Odds API quota counter (which
// only ticks on outbound calls anyway) or hammering Redis.
const REFRESH_INTERVAL_MS = 30 * 1000;

interface UseAdminInfoResult {
  data: AdminInfoResponse | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refetch: () => Promise<void>;
}

export function useAdminInfo(): UseAdminInfoResult {
  const [data, setData] = useState<AdminInfoResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Track which fetch is in flight so a slow first response doesn't
  // overwrite a fresher refresh response.
  const requestSeq = useRef(0);

  const fetchOnce = useCallback(async (initial: boolean) => {
    const mySeq = ++requestSeq.current;
    if (initial) setIsLoading(true);
    else setIsRefreshing(true);
    try {
      const res = await apiClient.get<AdminInfoResponse>('/admin/info');
      // Drop a stale response if a newer fetch already won the race.
      if (mySeq !== requestSeq.current) return;
      setData(res.data);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (mySeq !== requestSeq.current) return;
      let msg = 'Failed to load admin info.';
      if (isApiError(err)) {
        if (err.response?.status === 403) {
          msg = 'You do not have permission to view this page. Admin role required.';
        } else if (err.response?.status === 401) {
          msg = 'Not authenticated.';
        } else if (err.response?.data?.detail) {
          msg = String(err.response.data.detail);
        }
      }
      setError(msg);
    } finally {
      if (mySeq === requestSeq.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchOnce(true);
    const id = setInterval(() => fetchOnce(false), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchOnce]);

  const refetch = useCallback(() => fetchOnce(false), [fetchOnce]);

  return { data, isLoading, isRefreshing, error, lastUpdated, refetch };
}
