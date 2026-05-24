import { useCallback, useEffect, useState } from "react";

import { apiClient, isApiError } from "@/lib/apiClient";

export interface LeagueCsvFile {
  filename: string;
  size_bytes: number;
  last_modified: string | null;
}

interface UseLeagueCsvsResult {
  files: LeagueCsvFile[];
  isLoading: boolean;
  error: string | null;
  /** Triggers an immediate refetch for the current league. */
  refresh: () => Promise<void>;
  /** Deletes one CSV. Resolves once the server returns; the list is
   *  refetched automatically so callers don't need to call refresh too. */
  deleteFile: (filename: string) => Promise<void>;
}

/**
 * Per-league CSV listing for the Dixon-Coles admin page.
 *
 * The selected league can be a real slug, ``""`` (no selection), or the
 * "new league" sentinel from the page. We treat anything that isn't a
 * concrete slug as "don't fetch" — that keeps the listing empty while the
 * admin is typing a new slug into the input.
 */
export function useLeagueCsvs(league: string | null): UseLeagueCsvsResult {
  const [files, setFiles] = useState<LeagueCsvFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(league) && !league?.startsWith("__");

  const fetchOnce = useCallback(async () => {
    if (!enabled || !league) {
      setFiles([]);
      setError(null);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<LeagueCsvFile[]>(
        `/admin/dixon-coles/leagues/${encodeURIComponent(league)}/csvs`,
      );
      setFiles(res.data);
    } catch (err) {
      console.error("Failed to list CSVs for", league, err);
      const detail = isApiError(err)
        ? (err.response?.data as { detail?: string })?.detail
        : null;
      setError(detail ?? "Could not load uploaded CSVs.");
      setFiles([]);
    } finally {
      setIsLoading(false);
    }
  }, [enabled, league]);

  useEffect(() => {
    fetchOnce();
  }, [fetchOnce]);

  const deleteFile = useCallback(
    async (filename: string) => {
      if (!league || !enabled) return;
      // Optimistically remove from the list — re-fetched right after so a
      // failure re-syncs. This keeps the UI feeling instant on slow GCS
      // delete round-trips.
      setFiles((prev) => prev.filter((f) => f.filename !== filename));
      try {
        await apiClient.delete(
          `/admin/dixon-coles/leagues/${encodeURIComponent(
            league,
          )}/csvs/${encodeURIComponent(filename)}`,
        );
      } finally {
        // Always re-fetch — restores the row on a failed delete and
        // keeps mtimes / sizes truthful after a successful one.
        await fetchOnce();
      }
    },
    [league, enabled, fetchOnce],
  );

  return {
    files,
    isLoading,
    error,
    refresh: fetchOnce,
    deleteFile,
  };
}
