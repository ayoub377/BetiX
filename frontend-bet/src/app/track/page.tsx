"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, Clock, Info, Loader2, Lock, Sparkles, Target, Users } from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { apiClient, isApiError } from "@/lib/apiClient";
import { groupedLeaguesFor } from "@/lib/leagues";

type Sport = "football" | "tennis";

interface TrackResponse {
  match_id: string;
  status: string;
  meta?: Record<string, unknown>;
  message?: string;
}

const SPORTS: { value: Sport; label: string; placeholder: string; helper: string }[] = [
  {
    value: "football",
    label: "Football",
    placeholder: "e.g. Manchester United, Real Madrid",
    helper: "Enter the home team — we'll find their next upcoming fixture.",
  },
  {
    value: "tennis",
    label: "Tennis",
    placeholder: "e.g. Novak Djokovic, Carlos Alcaraz",
    helper: "Enter a player name — we'll find their next match.",
  },
];

export default function TrackPage() {
  const router = useRouter();
  const { firebaseUser, isLoadingAuth, customUserProfile } = useAuth();

  const [sport, setSport] = useState<Sport>("football");
  const [name, setName] = useState("");
  const [matchId, setMatchId] = useState("");
  // Empty string = "Auto-detect" (the default). When the user picks a
  // specific competition we forward it as ``sport_key`` to /odds/track
  // and the backend skips the multi-league fan-out lookup.
  const [sportKey, setSportKey] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"quota" | "kickoff" | "auth" | "other" | null>(null);

  // Football leagues and tennis tournaments don't overlap, so reset the
  // competition picker when the sport changes.
  useEffect(() => {
    setSportKey("");
  }, [sport]);

  const groupedLeagues = useMemo(() => groupedLeaguesFor(sport), [sport]);
  const competitionLabel = sport === "football" ? "Competition" : "Tournament";

  // Redirect to login if user clearly isn't authed.
  useEffect(() => {
    if (!isLoadingAuth && !firebaseUser) {
      router.replace("/auth/login?next=/track");
    }
  }, [isLoadingAuth, firebaseUser, router]);

  const role = customUserProfile?.role ?? "normal";
  const quotas = customUserProfile?.quotas;
  const concurrentLimit = quotas?.concurrent_tracker_limit ?? 1;
  const dailyTrackLimit = quotas?.daily_track_limit ?? 1;
  const lookaheadHours = quotas
    ? quotas.track_kickoff_lookahead_seconds === -1
      ? Infinity
      : Math.round(quotas.track_kickoff_lookahead_seconds / 3600)
    : 12;
  const pollMinutes = quotas ? Math.round(quotas.track_poll_interval_seconds / 60) : 45;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setErrorKind(null);

    const trimmedName = name.trim();
    const trimmedMatchId = matchId.trim();
    if (!trimmedName && !trimmedMatchId) {
      setErrorMessage("Enter a team / player name, or a FlashScore match ID.");
      setErrorKind("other");
      return;
    }

    setIsSubmitting(true);
    try {
      const body: Record<string, unknown> = { sport };
      if (sport === "football") {
        if (trimmedName) body.home_team = trimmedName;
      } else {
        if (trimmedName) body.player_name = trimmedName;
      }
      if (trimmedMatchId) body.match_id = trimmedMatchId;
      // Skip backend's multi-league fan-out lookup when the bettor has
      // told us exactly which competition to search.
      if (sportKey) body.sport_key = sportKey;

      const res = await apiClient.post<TrackResponse>("/odds/track", body);
      // Send the user to the Odds page with the new match selected.
      router.push(`/odds?match=${encodeURIComponent(res.data.match_id)}`);
    } catch (err) {
      console.error("Track failed:", err);
      if (isApiError(err) && err.response) {
        const status = err.response.status;
        const detail = (err.response.data as { detail?: string })?.detail ?? null;
        if (status === 401) {
          setErrorKind("auth");
          setErrorMessage("Your session expired. Please sign in again.");
        } else if (status === 429) {
          setErrorKind("quota");
          setErrorMessage(detail ?? "Daily tracking limit reached for your tier.");
        } else if (status === 403) {
          setErrorKind("kickoff");
          setErrorMessage(detail ?? "This match is outside your tracking window.");
        } else if (status === 404) {
          setErrorKind("other");
          setErrorMessage(detail ?? "Could not find a match for that input.");
        } else {
          setErrorKind("other");
          setErrorMessage(detail ?? "Could not start tracking. Try again.");
        }
      } else {
        setErrorKind("other");
        setErrorMessage("Network error. Try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoadingAuth || !firebaseUser) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-sky-500" />
      </div>
    );
  }

  const sportConfig = SPORTS.find((s) => s.value === sport)!;

  return (
    <div className="container mx-auto px-4 py-10 md:py-16 max-w-3xl">
      <header className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-50 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300 text-xs font-medium mb-4">
          <Activity className="h-3.5 w-3.5" />
          Live odds tracking
        </div>
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50">Track a match</h1>
        <p className="text-gray-600 dark:text-gray-400 mt-2">
          Pick a fixture and we'll snapshot odds every <strong>{pollMinutes} minutes</strong> until
          kickoff. History is preserved even after the match starts.
        </p>
      </header>

      {/* ─── Tier summary ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8">
        <TierStat
          icon={<Users className="h-4 w-4" />}
          label="Concurrent trackers"
          value={concurrentLimit === -1 ? "Unlimited" : `${concurrentLimit}`}
        />
        <TierStat
          icon={<Activity className="h-4 w-4" />}
          label="New tracks per day"
          value={dailyTrackLimit === -1 ? "Unlimited" : `${dailyTrackLimit}`}
        />
        <TierStat
          icon={<Clock className="h-4 w-4" />}
          label="Kickoff lookahead"
          value={lookaheadHours === Infinity ? "Unlimited" : `${lookaheadHours}h`}
        />
      </div>

      {/* ─── How it works ───────────────────────────────────────── */}
      <div className="mb-6 bg-sky-50 dark:bg-sky-900/20 border border-sky-200 dark:border-sky-800/40 text-sky-900 dark:text-sky-200 rounded-lg p-4 flex items-start gap-3 text-sm">
        <Info className="h-5 w-5 mt-0.5 flex-shrink-0 text-sky-600 dark:text-sky-400" />
        <div>
          <p className="font-medium mb-1">Team name is enough — but pin the competition for cleaner results.</p>
          <p className="text-sky-800 dark:text-sky-300/90 leading-relaxed">
            Leave the competition picker on <em>auto-detect</em> and we'll find the team's next
            fixture across every league. Picking a specific competition narrows the search to
            one league — faster, fewer Odds API calls, and avoids picking up the wrong fixture
            when a team plays in multiple competitions (cup vs. domestic, club vs. national).
          </p>
        </div>
      </div>

      {/* ─── Form ────────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 p-6 md:p-8 space-y-6">
        {/* Sport toggle */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">Sport</label>
          <div className="grid grid-cols-2 gap-2">
            {SPORTS.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => setSport(s.value)}
                className={`px-4 py-3 rounded-lg border-2 text-sm font-medium transition-all ${
                  sport === s.value
                    ? "border-sky-500 bg-sky-50 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300"
                    : "border-gray-200 dark:border-slate-600 text-gray-700 dark:text-gray-300 hover:border-gray-300 dark:hover:border-slate-500"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Name input */}
        <div>
          <label htmlFor="name" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
            {sport === "football" ? "Team name" : "Player name"}
          </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={sportConfig.placeholder}
            className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-sky-500 dark:focus:ring-sky-400 focus:border-sky-500 dark:bg-slate-700 dark:text-gray-100 text-base"
          />
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{sportConfig.helper}</p>
        </div>

        {/* Competition picker — optional override of the auto-discovery */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label htmlFor="competition" className="block text-sm font-medium text-gray-700 dark:text-gray-200 flex items-center gap-1.5">
              <Target className="h-4 w-4 text-gray-400 dark:text-gray-500" />
              {competitionLabel}
              <span className="text-gray-400 dark:text-gray-500 font-normal">(optional)</span>
            </label>
            {sportKey && (
              <button
                type="button"
                onClick={() => setSportKey("")}
                className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 underline-offset-2 hover:underline"
              >
                Clear
              </button>
            )}
          </div>
          <select
            id="competition"
            value={sportKey}
            onChange={(e) => setSportKey(e.target.value)}
            className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-sky-500 dark:focus:ring-sky-400 focus:border-sky-500 dark:bg-slate-700 dark:text-gray-100 text-base"
          >
            <option value="">Auto-detect competition</option>
            {groupedLeagues.map(({ group, options }) => (
              <optgroup key={group} label={group}>
                {options.map((o) => (
                  <option key={o.sport_key} value={o.sport_key}>
                    {o.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            {sportKey
              ? "We'll search this competition only — faster, fewer API calls, and avoids cross-competition ambiguity."
              : sport === "football"
              ? "Leave on auto-detect to scan every soccer league, or pick the competition you're betting on."
              : "Pick a Grand Slam if it's running now — otherwise leave on auto-detect."}
          </p>
        </div>

        {/* Optional match ID */}
        <details className="group">
          <summary className="text-sm text-gray-600 dark:text-gray-400 cursor-pointer hover:text-gray-900 dark:hover:text-gray-200">
            Have a FlashScore match ID? <span className="text-xs">(optional, advanced)</span>
          </summary>
          <div className="mt-3">
            <input
              type="text"
              value={matchId}
              onChange={(e) => setMatchId(e.target.value)}
              placeholder="e.g. 4ZuPXKbA"
              className="w-full px-4 py-2.5 border border-gray-300 dark:border-slate-600 rounded-lg text-sm dark:bg-slate-700 dark:text-gray-100"
            />
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
              Skip the lookup and track a specific match directly.
            </p>
          </div>
        </details>

        {/* Submit */}
        <button
          type="submit"
          disabled={isSubmitting || isLoadingAuth}
          className="w-full py-3 px-4 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Resolving match & starting tracker…
            </>
          ) : (
            "Start tracking"
          )}
        </button>

        {/* Error banner */}
        {errorMessage && (
          <ErrorBanner kind={errorKind!} message={errorMessage} role={role} onUpgrade={() => router.push("/pricing")} />
        )}
      </form>

      {/* ─── Help section ───────────────────────────────────────── */}
      <div className="mt-8 text-sm text-gray-500 dark:text-gray-400">
        <p>
          Once tracking starts you can monitor the match on the{" "}
          <a href="/odds" className="text-sky-600 dark:text-sky-400 hover:underline">
            Odds Tracker
          </a>{" "}
          page. Tracking automatically stops 5 minutes before kickoff and a final result is recorded
          when available.
        </p>
      </div>
    </div>
  );
}

function TierStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 p-4">
      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mb-1">
        {icon}
        <span>{label}</span>
      </div>
      <div className="text-lg font-semibold text-gray-900 dark:text-gray-50">{value}</div>
    </div>
  );
}

function ErrorBanner({
  kind,
  message,
  role,
  onUpgrade,
}: {
  kind: "quota" | "kickoff" | "auth" | "other";
  message: string;
  role: string;
  onUpgrade: () => void;
}) {
  const showUpgrade = (kind === "quota" || kind === "kickoff") && role === "normal";
  const Icon = kind === "auth" ? Lock : kind === "kickoff" ? Clock : AlertTriangle;
  const bg = kind === "kickoff" || kind === "quota"
    ? "bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-800/40 text-amber-900 dark:text-amber-200"
    : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/40 text-red-700 dark:text-red-300";

  return (
    <div className={`border rounded-lg p-4 ${bg}`}>
      <div className="flex items-start gap-3">
        <Icon className="h-5 w-5 mt-0.5 flex-shrink-0" />
        <div className="flex-1 text-sm">
          <p className="font-medium">{message}</p>
          {showUpgrade && (
            <button
              onClick={onUpgrade}
              className="mt-2 inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-300 hover:text-amber-900 dark:hover:text-amber-100 font-semibold underline-offset-2 hover:underline text-sm"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Upgrade to Premium for higher limits
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
