"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Brain, Loader2, AlertTriangle, Sparkles } from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { apiClient, isApiError } from "@/lib/apiClient";

interface PredictionResponse {
  home_team: string;
  away_team: string;
  league_name?: string;
  home_win_probability: number;
  draw_probability: number;
  away_win_probability: number;
  expected_home_goals?: number;
  expected_away_goals?: number;
  // Anything else the model returns is preserved but not rendered.
  [k: string]: unknown;
}

interface TeamListResponse {
  league: string;
  teams: string[];
}

export default function PredictionsPage() {
  const router = useRouter();
  const { firebaseUser, isLoadingAuth, customUserProfile, requestsLeftToday } = useAuth();

  const [leagues, setLeagues] = useState<string[]>([]);
  const [leagueLoading, setLeagueLoading] = useState(false);
  const [selectedLeague, setSelectedLeague] = useState<string>("");
  const [teams, setTeams] = useState<string[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(false);
  const [home, setHome] = useState<string>("");
  const [away, setAway] = useState<string>("");

  const [prediction, setPrediction] = useState<PredictionResponse | null>(null);
  const [isPredicting, setIsPredicting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const role = customUserProfile?.role ?? "normal";
  const dailyLimit = customUserProfile?.quotas.daily_predict_limit ?? 5;

  // Auth gate
  useEffect(() => {
    if (!isLoadingAuth && !firebaseUser) {
      router.replace("/auth/login?next=/predictions");
    }
  }, [isLoadingAuth, firebaseUser, router]);

  // Load leagues on mount
  useEffect(() => {
    if (!firebaseUser) return;
    setLeagueLoading(true);
    apiClient
      .get<{ models?: string[] } | string[]>("/predictions/leagues")
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : res.data.models ?? [];
        setLeagues(list);
        if (list.length > 0) setSelectedLeague(list[0]);
      })
      .catch((err) => {
        console.error("Failed to load leagues:", err);
        setErrorMessage("Could not load available leagues. Try refreshing.");
      })
      .finally(() => setLeagueLoading(false));
  }, [firebaseUser]);

  // Load teams whenever league changes
  useEffect(() => {
    if (!selectedLeague) return;
    setTeamsLoading(true);
    setHome("");
    setAway("");
    apiClient
      .get<TeamListResponse>(`/predictions/teams/${encodeURIComponent(selectedLeague)}`)
      .then((res) => {
        setTeams(res.data.teams ?? []);
      })
      .catch((err) => {
        console.error("Failed to load teams:", err);
        setTeams([]);
      })
      .finally(() => setTeamsLoading(false));
  }, [selectedLeague]);

  const canSubmit = !!selectedLeague && !!home && !!away && home !== away && !isPredicting;

  const handlePredict = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsPredicting(true);
    setErrorMessage(null);
    setPrediction(null);
    try {
      const res = await apiClient.post<PredictionResponse>("/predictions/predict", {
        league_name: selectedLeague,
        home_team: home,
        away_team: away,
      });
      setPrediction(res.data);
    } catch (err) {
      console.error("Predict failed:", err);
      if (isApiError(err) && err.response) {
        const detail = (err.response.data as { detail?: string })?.detail;
        if (err.response.status === 429) {
          setErrorMessage(detail ?? `Daily prediction limit reached (${dailyLimit}/day for ${role}).`);
        } else if (err.response.status === 404) {
          setErrorMessage(detail ?? "League or team not found in the trained model.");
        } else {
          setErrorMessage(detail ?? "Could not compute prediction.");
        }
      } else {
        setErrorMessage("Network error. Try again.");
      }
    } finally {
      setIsPredicting(false);
    }
  };

  if (isLoadingAuth || !firebaseUser) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-10 md:py-16 max-w-4xl">
      <header className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-xs font-medium mb-4">
          <Brain className="h-3.5 w-3.5" />
          Dixon-Coles statistical model
        </div>
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50">Match predictions</h1>
        <p className="text-gray-600 dark:text-gray-400 mt-2">
          Pick a league and two teams. The model returns home-win, draw, and away-win
          probabilities based on historical team strength.
        </p>
        {role !== "admin" && (
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Daily predictions remaining:{" "}
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              {requestsLeftToday === Infinity ? "Unlimited" : Math.max(0, requestsLeftToday)} / {dailyLimit}
            </span>
          </p>
        )}
      </header>

      <form onSubmit={handlePredict} className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 p-6 md:p-8 space-y-6">
        {/* League */}
        <div>
          <label htmlFor="league" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
            League
          </label>
          <select
            id="league"
            value={selectedLeague}
            onChange={(e) => setSelectedLeague(e.target.value)}
            disabled={leagueLoading || leagues.length === 0}
            className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-emerald-500 dark:focus:ring-emerald-400 focus:border-emerald-500 dark:bg-slate-700 dark:text-gray-100 text-base disabled:opacity-60"
          >
            {leagueLoading && <option>Loading…</option>}
            {!leagueLoading && leagues.length === 0 && <option>No trained models available</option>}
            {leagues.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>

        {/* Teams */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TeamPicker
            id="home"
            label="Home team"
            teams={teams}
            value={home}
            onChange={setHome}
            disabled={teamsLoading || teams.length === 0}
          />
          <TeamPicker
            id="away"
            label="Away team"
            teams={teams}
            value={away}
            onChange={setAway}
            disabled={teamsLoading || teams.length === 0}
            excludeTeam={home}
          />
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full py-3 px-4 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center"
        >
          {isPredicting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Computing…
            </>
          ) : (
            "Predict outcome"
          )}
        </button>

        {errorMessage && (
          <div className="border border-red-200 dark:border-red-800/40 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg p-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 mt-0.5 flex-shrink-0" />
            <div className="flex-1 text-sm">
              <p>{errorMessage}</p>
              {role === "normal" && errorMessage.toLowerCase().includes("limit") && (
                <button
                  type="button"
                  onClick={() => router.push("/pricing")}
                  className="mt-2 inline-flex items-center gap-1.5 font-semibold underline-offset-2 hover:underline"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  Upgrade for 100 daily predictions
                </button>
              )}
            </div>
          </div>
        )}
      </form>

      {prediction && <PredictionResult prediction={prediction} />}
    </div>
  );
}

function TeamPicker({
  id,
  label,
  teams,
  value,
  onChange,
  disabled,
  excludeTeam,
}: {
  id: string;
  label: string;
  teams: string[];
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  excludeTeam?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 dark:bg-slate-700 dark:text-gray-100 text-base disabled:opacity-60"
      >
        <option value="">Select a team…</option>
        {teams
          .filter((t) => t !== excludeTeam)
          .map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
      </select>
    </div>
  );
}

function PredictionResult({ prediction }: { prediction: PredictionResponse }) {
  const home = clampPct(prediction.home_win_probability);
  const draw = clampPct(prediction.draw_probability);
  const away = clampPct(prediction.away_win_probability);
  const winner =
    home >= draw && home >= away ? "home" : away >= home && away >= draw ? "away" : "draw";

  return (
    <div className="mt-8 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 p-6 md:p-8">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50 mb-1">
        {prediction.home_team} <span className="text-gray-400">vs</span> {prediction.away_team}
      </h2>
      {prediction.league_name && (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">{prediction.league_name}</p>
      )}

      <div className="space-y-4">
        <ProbabilityBar
          label={prediction.home_team}
          subtitle="Home win"
          value={home}
          accent="from-sky-500 to-blue-600"
          highlight={winner === "home"}
        />
        <ProbabilityBar
          label="Draw"
          value={draw}
          accent="from-gray-400 to-gray-500"
          highlight={winner === "draw"}
        />
        <ProbabilityBar
          label={prediction.away_team}
          subtitle="Away win"
          value={away}
          accent="from-amber-500 to-orange-600"
          highlight={winner === "away"}
        />
      </div>

      {(prediction.expected_home_goals !== undefined ||
        prediction.expected_away_goals !== undefined) && (
        <div className="mt-6 pt-6 border-t border-gray-100 dark:border-slate-700 grid grid-cols-2 gap-4 text-sm">
          {prediction.expected_home_goals !== undefined && (
            <div>
              <div className="text-gray-500 dark:text-gray-400 mb-1">Expected goals (home)</div>
              <div className="text-2xl font-semibold text-gray-900 dark:text-gray-50">
                {prediction.expected_home_goals.toFixed(2)}
              </div>
            </div>
          )}
          {prediction.expected_away_goals !== undefined && (
            <div>
              <div className="text-gray-500 dark:text-gray-400 mb-1">Expected goals (away)</div>
              <div className="text-2xl font-semibold text-gray-900 dark:text-gray-50">
                {prediction.expected_away_goals.toFixed(2)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ProbabilityBar({
  label,
  subtitle,
  value,
  accent,
  highlight,
}: {
  label: string;
  subtitle?: string;
  value: number;
  accent: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div>
          <span className={`font-medium ${highlight ? "text-gray-900 dark:text-gray-50" : "text-gray-700 dark:text-gray-300"}`}>
            {label}
          </span>
          {subtitle && <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{subtitle}</span>}
        </div>
        <span className={`text-sm font-semibold ${highlight ? "text-gray-900 dark:text-gray-50" : "text-gray-600 dark:text-gray-400"}`}>
          {(value * 100).toFixed(1)}%
        </span>
      </div>
      <div className="h-3 rounded-full bg-gray-100 dark:bg-slate-700 overflow-hidden">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${accent} transition-all duration-500`}
          style={{ width: `${Math.max(2, value * 100)}%` }}
        />
      </div>
    </div>
  );
}

function clampPct(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.min(Math.max(n, 0), 1);
}
