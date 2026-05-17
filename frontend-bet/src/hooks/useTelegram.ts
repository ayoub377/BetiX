// Hook that owns all Telegram-alert state for the dashboard card.
//
// Surface:
//   status          – latest server-known state (or null while loading)
//   isLoading       – true while the initial /status fetch is in flight
//   error           – last error message from any call, cleared on retry
//   connect()       – mint a deep-link, open it, then poll /status until linked
//   disconnect()    – clear the saved chat_id server-side
//   savePreferences – update threshold_pct and/or enabled
//   refresh         – force-refetch status (cheap; used after window focus)
//
// Polling is bounded: after the user clicks Connect we poll every 2s for
// up to 5 minutes, then give up. That covers the realistic case (user taps
// Start within seconds) without hanging an open request forever if they
// close the Telegram tab.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient, isApiError } from "@/lib/apiClient";
import type {
  TelegramLinkResponse,
  TelegramPreferencesUpdate,
  TelegramStatus,
} from "@/types/telegram";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_DURATION_MS = 5 * 60 * 1000;

function extractApiError(err: unknown, fallback: string): string {
  if (isApiError(err)) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return fallback;
}

export function useTelegram(opts: { enabled: boolean }) {
  // ``enabled`` mirrors "user is authenticated and we want this hook to run".
  // We pass it explicitly rather than calling useAuth() inside so the hook
  // remains usable in isolated previews / Storybook later.
  const { enabled } = opts;

  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ref instead of state so we can clear an in-flight poll on unmount without
  // re-triggering renders.
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollDeadlineRef = useRef<number>(0);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const refresh = useCallback(async (): Promise<TelegramStatus | null> => {
    if (!enabled) return null;
    try {
      const res = await apiClient.get<TelegramStatus>("/telegram/status");
      setStatus(res.data);
      return res.data;
    } catch (err) {
      setError(extractApiError(err, "Could not load Telegram status."));
      return null;
    }
  }, [enabled]);

  // Initial load.
  useEffect(() => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    refresh().finally(() => setIsLoading(false));
  }, [enabled, refresh]);

  // Re-fetch on window focus — covers the case where the user finishes the
  // Telegram handshake in another tab and switches back.
  useEffect(() => {
    if (!enabled) return;
    const onFocus = () => {
      refresh();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled, refresh]);

  // Clean up any pending poll when the component unmounts.
  useEffect(() => () => stopPolling(), [stopPolling]);

  const connect = useCallback(async (): Promise<void> => {
    setError(null);
    setIsConnecting(true);
    try {
      const res = await apiClient.post<TelegramLinkResponse>("/telegram/link");
      // Open in a new tab. We rely on user-initiated click here, so the
      // popup blocker won't intervene. If it does, surface the deep-link
      // so the user can copy it manually.
      const win = window.open(res.data.deep_link, "_blank", "noopener,noreferrer");
      if (!win) {
        setError(
          `Pop-up blocked. Open this link manually: ${res.data.deep_link}`,
        );
        setIsConnecting(false);
        return;
      }

      // Start polling /status. Stop as soon as we see ``linked: true`` or
      // after POLL_MAX_DURATION_MS.
      stopPolling();
      pollDeadlineRef.current = Date.now() + POLL_MAX_DURATION_MS;
      pollTimerRef.current = setInterval(async () => {
        const fresh = await refresh();
        if (fresh?.linked) {
          stopPolling();
          setIsConnecting(false);
          return;
        }
        if (Date.now() > pollDeadlineRef.current) {
          stopPolling();
          setIsConnecting(false);
          setError(
            "Didn't see the Telegram handshake within 5 minutes. " +
              "Click Connect again to retry.",
          );
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      setError(extractApiError(err, "Could not start Telegram link flow."));
      setIsConnecting(false);
    }
  }, [refresh, stopPolling]);

  const disconnect = useCallback(async (): Promise<void> => {
    setError(null);
    setIsSaving(true);
    try {
      await apiClient.post("/telegram/unlink");
      await refresh();
    } catch (err) {
      setError(extractApiError(err, "Could not disconnect Telegram."));
    } finally {
      setIsSaving(false);
    }
  }, [refresh]);

  const savePreferences = useCallback(
    async (payload: TelegramPreferencesUpdate): Promise<boolean> => {
      setError(null);
      setIsSaving(true);
      try {
        const res = await apiClient.patch<TelegramStatus>(
          "/telegram/preferences",
          payload,
        );
        setStatus(res.data);
        return true;
      } catch (err) {
        setError(extractApiError(err, "Could not save your preferences."));
        return false;
      } finally {
        setIsSaving(false);
      }
    },
    [],
  );

  // Confirmation flash that the parent component renders as a transient
  // "Sent! Check your DMs" banner. Separate from `error` so the two can
  // coexist (e.g. a previous error doesn't get clobbered by a success).
  const [lastTestResult, setLastTestResult] = useState<
    { ok: true } | { ok: false; message: string } | null
  >(null);
  const [isSendingTest, setIsSendingTest] = useState(false);

  const sendTestAlert = useCallback(async (): Promise<boolean> => {
    setLastTestResult(null);
    setIsSendingTest(true);
    try {
      await apiClient.post("/telegram/test");
      setLastTestResult({ ok: true });
      return true;
    } catch (err) {
      const message = extractApiError(err, "Could not send a test alert.");
      setLastTestResult({ ok: false, message });
      return false;
    } finally {
      setIsSendingTest(false);
    }
  }, []);

  return {
    status,
    isLoading,
    isConnecting,
    isSaving,
    isSendingTest,
    error,
    lastTestResult,
    connect,
    disconnect,
    savePreferences,
    sendTestAlert,
    refresh,
    clearError: () => setError(null),
    clearTestResult: () => setLastTestResult(null),
  };
}
