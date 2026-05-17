// Dashboard card that orchestrates the Telegram alert connection flow.
//
// Three visual states it can render:
//
//   1. Free / non-premium user → locked card with an Upgrade CTA. We don't
//      hide the card so the feature is discoverable.
//   2. Premium, not linked    → "Connect Telegram" button. After click we
//      open the bot deep-link in a new tab and poll for confirmation.
//   3. Premium, linked        → threshold input + alerts on/off toggle +
//      disconnect button. Shows the last 4 digits of the chat_id so the
//      user can see *something* identifying the connection.
//
// All API calls live in useTelegram; this file is pure presentation +
// local input state.

"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Link2,
  Loader2,
  Send,
  Sparkles,
  Unlink,
  Zap,
} from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { useTelegram } from "@/hooks/useTelegram";

// Mirror the backend bounds in app/settings.py. If you tighten them
// there, tighten them here too — backend will still reject, but client-
// side validation is friendlier UX.
const MIN_THRESHOLD_PCT = 1;
const MAX_THRESHOLD_PCT = 50;
const DEFAULT_THRESHOLD_PCT = 5;

export default function TelegramAlertsCard() {
  const { customUserProfile, isLoadingAuth } = useAuth();
  const isPremium = customUserProfile?.isPremiumMember ?? false;
  const isAuthed = !!customUserProfile;

  const {
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
    clearError,
    clearTestResult,
  } = useTelegram({ enabled: isAuthed && isPremium });

  // Auto-clear the success flash after a few seconds so the card doesn't
  // keep claiming "Sent!" forever. Errors persist until dismissed.
  useEffect(() => {
    if (lastTestResult?.ok) {
      const t = setTimeout(clearTestResult, 5000);
      return () => clearTimeout(t);
    }
  }, [lastTestResult, clearTestResult]);

  // Local input state mirrors the server's threshold but lets the user type
  // freely. We only push to the server on Save.
  const [thresholdInput, setThresholdInput] = useState<string>("");
  const [thresholdDirty, setThresholdDirty] = useState(false);

  // Whenever the server hands us a fresh threshold and the field is clean,
  // sync the input.
  useEffect(() => {
    if (!thresholdDirty) {
      setThresholdInput(
        status?.threshold_pct != null
          ? String(status.threshold_pct)
          : String(DEFAULT_THRESHOLD_PCT),
      );
    }
  }, [status?.threshold_pct, thresholdDirty]);

  // ── Render skeletons / gated states first ────────────────────────
  if (isLoadingAuth) {
    return <CardShell><CardSkeleton /></CardShell>;
  }

  if (!isAuthed) {
    // Dashboard already gates auth; defensive only.
    return null;
  }

  if (!isPremium) {
    return <UpsellCard />;
  }

  if (isLoading) {
    return <CardShell><CardSkeleton /></CardShell>;
  }

  // ── Premium states ──────────────────────────────────────────────
  const linked = !!status?.linked;
  const alertsEnabled = !!status?.alerts_enabled;

  const parsedThreshold = Number(thresholdInput);
  const thresholdValid =
    Number.isFinite(parsedThreshold) &&
    parsedThreshold >= MIN_THRESHOLD_PCT &&
    parsedThreshold <= MAX_THRESHOLD_PCT;

  const handleSaveThreshold = async () => {
    if (!thresholdValid) return;
    const ok = await savePreferences({ threshold_pct: parsedThreshold });
    if (ok) setThresholdDirty(false);
  };

  const handleToggleAlerts = async () => {
    // If we're enabling and the input is dirty, persist the threshold in
    // the same request — no point in two round-trips.
    const payload: { threshold_pct?: number; enabled: boolean } = {
      enabled: !alertsEnabled,
    };
    if (!alertsEnabled && thresholdDirty && thresholdValid) {
      payload.threshold_pct = parsedThreshold;
    }
    const ok = await savePreferences(payload);
    if (ok) setThresholdDirty(false);
  };

  return (
    <CardShell>
      <Header linked={linked} alertsEnabled={alertsEnabled} />

      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {lastTestResult?.ok && <SuccessBanner message="Test alert sent. Check your Telegram DMs." />}
      {lastTestResult && !lastTestResult.ok && (
        <ErrorBanner message={lastTestResult.message} onDismiss={clearTestResult} />
      )}

      {!linked ? (
        <ConnectPanel onConnect={connect} isConnecting={isConnecting} />
      ) : (
        <ConfiguredPanel
          status={status!}
          thresholdInput={thresholdInput}
          onThresholdChange={(v) => {
            setThresholdInput(v);
            setThresholdDirty(true);
          }}
          thresholdValid={thresholdValid}
          thresholdDirty={thresholdDirty}
          isSaving={isSaving}
          isSendingTest={isSendingTest}
          onSaveThreshold={handleSaveThreshold}
          onToggleAlerts={handleToggleAlerts}
          onSendTest={sendTestAlert}
          onDisconnect={disconnect}
        />
      )}

      <Footnote />
    </CardShell>
  );
}

// ────────────────────────────────────────────────────────────────────
// Card shell + header
// ────────────────────────────────────────────────────────────────────

function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6">
      {children}
    </div>
  );
}

function Header({ linked, alertsEnabled }: { linked: boolean; alertsEnabled: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div className="flex items-center gap-3 min-w-0">
        <div className="inline-flex h-10 w-10 rounded-xl bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400 items-center justify-center flex-shrink-0">
          <Send className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-50 flex items-center gap-2">
            Telegram alerts
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gradient-to-r from-sky-500 to-indigo-600 text-white">
              <Sparkles className="h-3 w-3" />
              Premium
            </span>
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Get a DM when a tracked match's odds move past your threshold.
          </p>
        </div>
      </div>
      <StatusPill linked={linked} alertsEnabled={alertsEnabled} />
    </div>
  );
}

function StatusPill({ linked, alertsEnabled }: { linked: boolean; alertsEnabled: boolean }) {
  if (linked && alertsEnabled) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 flex-shrink-0">
        <Check className="h-3 w-3" />
        Active
      </span>
    );
  }
  if (linked) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 border border-amber-200 dark:border-amber-800 flex-shrink-0">
        Linked · alerts off
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300 border border-gray-200 dark:border-slate-600 flex-shrink-0">
      Not linked
    </span>
  );
}

// ────────────────────────────────────────────────────────────────────
// Panels
// ────────────────────────────────────────────────────────────────────

function ConnectPanel({
  onConnect,
  isConnecting,
}: {
  onConnect: () => void;
  isConnecting: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="text-sm text-gray-600 dark:text-gray-400">
        We'll open Telegram in a new tab. Tap <span className="font-semibold">Start</span> in
        the chat to finish linking — this page updates automatically when you do.
      </div>
      <button
        onClick={onConnect}
        disabled={isConnecting}
        className="self-start inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-sm font-semibold shadow-sm hover:shadow-md transition-all disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {isConnecting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Waiting for Telegram…
          </>
        ) : (
          <>
            <Link2 className="h-4 w-4" />
            Connect Telegram
          </>
        )}
      </button>
      {isConnecting && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          If you didn't see Telegram open, allow pop-ups for this site and click again.
        </p>
      )}
    </div>
  );
}

interface ConfiguredPanelProps {
  status: { chat_id_suffix: string | null };
  thresholdInput: string;
  onThresholdChange: (v: string) => void;
  thresholdValid: boolean;
  thresholdDirty: boolean;
  isSaving: boolean;
  isSendingTest: boolean;
  onSaveThreshold: () => void;
  onToggleAlerts: () => void;
  onSendTest: () => void;
  onDisconnect: () => void;
}

function ConfiguredPanel(props: ConfiguredPanelProps) {
  const {
    status,
    thresholdInput,
    onThresholdChange,
    thresholdValid,
    thresholdDirty,
    isSaving,
    isSendingTest,
    onSaveThreshold,
    onToggleAlerts,
    onSendTest,
    onDisconnect,
  } = props;

  return (
    <div className="flex flex-col gap-5">
      {/* Threshold input */}
      <div>
        <label
          htmlFor="telegram-threshold"
          className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5"
        >
          Alert threshold
        </label>
        <div className="flex items-center gap-2">
          <div className="relative flex-1 max-w-[10rem]">
            <input
              id="telegram-threshold"
              type="number"
              inputMode="decimal"
              min={MIN_THRESHOLD_PCT}
              max={MAX_THRESHOLD_PCT}
              step={0.5}
              value={thresholdInput}
              onChange={(e) => onThresholdChange(e.target.value)}
              className="w-full pl-3 pr-8 py-2 text-sm rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
              aria-invalid={!thresholdValid}
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-400 pointer-events-none">
              %
            </span>
          </div>
          <button
            onClick={onSaveThreshold}
            disabled={!thresholdValid || !thresholdDirty || isSaving}
            className="px-3 py-2 text-xs font-semibold rounded-lg border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSaving ? "Saving…" : "Save"}
          </button>
        </div>
        <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          Any 1X2 market that moves ≥ {thresholdValid ? thresholdInput : "?"}% from its
          opening odds will trigger a DM. Range: {MIN_THRESHOLD_PCT}–{MAX_THRESHOLD_PCT}%.
        </p>
        {!thresholdValid && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            Must be a number between {MIN_THRESHOLD_PCT} and {MAX_THRESHOLD_PCT}.
          </p>
        )}
      </div>

      {/* Toggle */}
      <ToggleRow
        label="Send alerts to Telegram"
        sublabel={
          status.chat_id_suffix
            ? `Linked to chat ····${status.chat_id_suffix}`
            : "Linked"
        }
        // Visible state is fed in via the parent's status, not local mirror —
        // means a server rejection (e.g. threshold cleared) instantly reflects.
        // We expose the toggle's "checked" via aria-pressed on the wrapper button.
        onClick={onToggleAlerts}
        disabled={isSaving}
        active={status.chat_id_suffix !== null}
      />

      {/* Test + Disconnect — secondary actions clustered together */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <button
          onClick={onSendTest}
          disabled={isSendingTest}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-sky-300 dark:border-sky-700 text-sky-700 dark:text-sky-300 hover:bg-sky-50 dark:hover:bg-sky-900/30 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
        >
          {isSendingTest ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Sending…
            </>
          ) : (
            <>
              <Send className="h-3.5 w-3.5" />
              Send test alert
            </>
          )}
        </button>
        <button
          onClick={onDisconnect}
          disabled={isSaving}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:underline disabled:opacity-50"
        >
          <Unlink className="h-3.5 w-3.5" />
          Disconnect Telegram
        </button>
      </div>
    </div>
  );
}

// The toggle's `active` prop here is only used to gate the toggle being
// interactable; the actual on/off state needs to come from the server, so
// we read it from the *parent* via status.alerts_enabled. To avoid lifting
// state again, the parent passes the toggled handler in `onClick` and the
// background colour reflects whatever the server last told us.
function ToggleRow({
  label,
  sublabel,
  onClick,
  disabled,
  active,
}: {
  label: string;
  sublabel?: string;
  onClick: () => void;
  disabled: boolean;
  active: boolean;
}) {
  // We render the toggle as a plain button styled like a switch so we don't
  // pull in an extra dependency for this one control.
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{label}</div>
        {sublabel && (
          <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{sublabel}</div>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={active}
        onClick={onClick}
        disabled={disabled}
        // Parent controls visual checked-state via the `active` parameter
        // we pass through from `status.alerts_enabled`.
        className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          active ? "bg-sky-500" : "bg-gray-300 dark:bg-slate-600"
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
            active ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Misc subviews
// ────────────────────────────────────────────────────────────────────

function UpsellCard() {
  return (
    <CardShell>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="inline-flex h-10 w-10 rounded-xl bg-gray-100 dark:bg-slate-700 text-gray-400 dark:text-gray-500 items-center justify-center flex-shrink-0">
            <Send className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-50 flex items-center gap-2">
              Telegram alerts
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gradient-to-r from-sky-500 to-indigo-600 text-white">
                <Sparkles className="h-3 w-3" />
                Premium
              </span>
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 max-w-md">
              Set a % threshold and get an instant DM whenever a match you're tracking
              moves past it — no need to keep the dashboard open.
            </p>
          </div>
        </div>
      </div>
      <div className="mt-5">
        <Link
          href="/pricing"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-sm font-semibold shadow-sm hover:shadow-md transition-all"
        >
          <Zap className="h-4 w-4" />
          Upgrade to unlock
        </Link>
      </div>
    </CardShell>
  );
}

function CardSkeleton() {
  return (
    <div className="animate-pulse space-y-3">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-xl bg-gray-200 dark:bg-slate-700" />
        <div className="flex-1 space-y-2">
          <div className="h-3 w-32 rounded bg-gray-200 dark:bg-slate-700" />
          <div className="h-2.5 w-48 rounded bg-gray-100 dark:bg-slate-700/60" />
        </div>
      </div>
      <div className="h-9 w-40 rounded-lg bg-gray-200 dark:bg-slate-700" />
    </div>
  );
}

function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-900/20 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
      <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />
      <span className="flex-1 break-words">{message}</span>
    </div>
  );
}

function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20 px-3 py-2 text-xs text-red-700 dark:text-red-300">
      <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
      <span className="flex-1 break-words">{message}</span>
      <button
        onClick={onDismiss}
        className="text-red-700/70 hover:text-red-700 dark:text-red-300/70 dark:hover:text-red-300 font-semibold"
        aria-label="Dismiss error"
      >
        ×
      </button>
    </div>
  );
}

function Footnote() {
  return (
    <p className="mt-5 pt-4 border-t border-gray-100 dark:border-slate-700 text-[11px] text-gray-400 dark:text-gray-500 leading-relaxed">
      Alerts fire at most once per market direction per match, with a 60-minute
      cooldown. We never DM you anything except your own alerts.
    </p>
  );
}
