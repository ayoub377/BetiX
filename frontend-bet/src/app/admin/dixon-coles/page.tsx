"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileUp,
  Loader2,
  Play,
  RefreshCcw,
  ShieldAlert,
  Upload,
} from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { apiClient, isApiError } from "@/lib/apiClient";
import LeagueCsvManager from "@/components/admin/LeagueCsvManager";

interface LeagueOverview {
  league: string;
  csv_count: number;
  last_uploaded: string | null;
  model_trained: boolean;
  model_last_trained: string | null;
}

interface UploadResponse {
  league: string;
  filename: string;
  rows: number;
  stored_at: string;
}

interface TrainResponse {
  status: string;
  message: string;
  model_path?: string | null;
}

type Toast = { kind: "ok" | "error"; text: string } | null;

const NEW_LEAGUE_SENTINEL = "__new__";

export default function AdminDixonColesPage() {
  const router = useRouter();
  const { firebaseUser, customUserProfile, isLoadingAuth } = useAuth();

  const [leagues, setLeagues] = useState<LeagueOverview[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [selectedLeague, setSelectedLeague] = useState<string>("");
  const [newLeagueSlug, setNewLeagueSlug] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [uploading, setUploading] = useState(false);
  const [trainingLeague, setTrainingLeague] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast>(null);

  // Resolve the effective league slug from the picker.
  const effectiveLeague = useMemo(() => {
    if (selectedLeague === NEW_LEAGUE_SENTINEL) {
      return newLeagueSlug.trim().toLowerCase().replace(/\s+/g, "_");
    }
    return selectedLeague;
  }, [selectedLeague, newLeagueSlug]);

  // ─── Auth gates ────────────────────────────────────────────────────────
  useEffect(() => {
    if (isLoadingAuth) return;
    if (!firebaseUser) {
      router.replace("/auth/login?next=/admin/dixon-coles");
    }
  }, [isLoadingAuth, firebaseUser, router]);

  const role = customUserProfile?.role ?? "normal";
  const isAdmin = role === "admin";

  // ─── Fetch leagues ─────────────────────────────────────────────────────
  const refreshLeagues = useCallback(async () => {
    if (!isAdmin) return;
    setOverviewLoading(true);
    setOverviewError(null);
    try {
      const res = await apiClient.get<LeagueOverview[]>("/admin/dixon-coles/leagues");
      setLeagues(res.data);
      // Default the picker to the first league if nothing is selected yet.
      setSelectedLeague((prev) => {
        if (prev) return prev;
        return res.data.length > 0 ? res.data[0].league : NEW_LEAGUE_SENTINEL;
      });
    } catch (err) {
      console.error("Failed to fetch admin leagues:", err);
      const detail = isApiError(err) ? (err.response?.data as { detail?: string })?.detail : null;
      setOverviewError(detail ?? "Could not load leagues.");
    } finally {
      setOverviewLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin) {
      refreshLeagues();
    }
  }, [isAdmin, refreshLeagues]);

  // ─── Upload ────────────────────────────────────────────────────────────
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    setToast(null);

    if (!effectiveLeague) {
      setToast({ kind: "error", text: "Pick a league or type a new league slug." });
      return;
    }
    if (!file) {
      setToast({ kind: "error", text: "Choose a CSV file to upload." });
      return;
    }

    const form = new FormData();
    form.append("file", file);

    setUploading(true);
    try {
      const res = await apiClient.post<UploadResponse>(
        `/admin/dixon-coles/leagues/${encodeURIComponent(effectiveLeague)}/upload`,
        form,
      );
      setToast({
        kind: "ok",
        text: `Uploaded ${res.data.filename} → ${res.data.league} (${res.data.rows} rows).`,
      });
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      // If this was a brand-new league, make it the active selection.
      if (selectedLeague === NEW_LEAGUE_SENTINEL) {
        setSelectedLeague(res.data.league);
        setNewLeagueSlug("");
      }
      await refreshLeagues();
    } catch (err) {
      console.error("Upload failed:", err);
      const detail = isApiError(err) ? (err.response?.data as { detail?: string })?.detail : null;
      setToast({ kind: "error", text: detail ?? "Upload failed." });
    } finally {
      setUploading(false);
    }
  };

  // ─── Train ─────────────────────────────────────────────────────────────
  const handleTrain = async (league: string) => {
    setToast(null);
    setTrainingLeague(league);
    try {
      const res = await apiClient.post<TrainResponse>(
        `/admin/dixon-coles/leagues/${encodeURIComponent(league)}/train`,
        null,
        { params: { force_refit: true }, timeout: 5 * 60 * 1000 },
      );
      setToast({ kind: "ok", text: res.data.message });
      await refreshLeagues();
    } catch (err) {
      console.error("Train failed:", err);
      const detail = isApiError(err) ? (err.response?.data as { detail?: string })?.detail : null;
      setToast({ kind: "error", text: detail ?? "Training failed." });
    } finally {
      setTrainingLeague(null);
    }
  };

  // ─── Loading / 403 states ──────────────────────────────────────────────
  if (isLoadingAuth || !firebaseUser) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="container mx-auto px-4 py-16 max-w-2xl">
        <div className="rounded-2xl border border-amber-200 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-900/20 p-6 flex items-start gap-3">
          <ShieldAlert className="h-6 w-6 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <h1 className="font-semibold text-amber-900 dark:text-amber-100">Admin access required</h1>
            <p className="text-sm text-amber-800 dark:text-amber-200 mt-1">
              You're signed in as <span className="font-medium">{customUserProfile?.email ?? "—"}</span>{" "}
              with role <span className="font-medium">{role}</span>. Only admins can manage
              Dixon-Coles training data.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-10 md:py-16 max-w-5xl">
      <header className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-xs font-medium mb-4">
          <Database className="h-3.5 w-3.5" />
          Admin · Dixon-Coles
        </div>
        <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50">
          Training data &amp; models
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mt-2 max-w-2xl">
          Upload season CSVs (football-data.co.uk format) per league, then retrain the
          model. Trained models are picked up automatically by{" "}
          <span className="font-mono text-sm">/api/predictions/predict</span>.
        </p>
      </header>

      {/* Upload form */}
      <section className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 p-6 md:p-8 space-y-6">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-50">
          <FileUp className="h-5 w-5 text-emerald-500" />
          Upload a CSV
        </h2>

        <form onSubmit={handleUpload} className="space-y-4">
          <div>
            <label htmlFor="league" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
              League
            </label>
            <select
              id="league"
              value={selectedLeague}
              onChange={(e) => setSelectedLeague(e.target.value)}
              className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 dark:bg-slate-700 dark:text-gray-100 text-base"
            >
              {leagues.map((l) => (
                <option key={l.league} value={l.league}>
                  {l.league} · {l.csv_count} CSV{l.csv_count === 1 ? "" : "s"}
                  {l.model_trained ? " · model ready" : ""}
                </option>
              ))}
              <option value={NEW_LEAGUE_SENTINEL}>➕ New league…</option>
            </select>
          </div>

          {selectedLeague === NEW_LEAGUE_SENTINEL && (
            <div>
              <label htmlFor="new-league" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
                New league slug
              </label>
              <input
                id="new-league"
                type="text"
                value={newLeagueSlug}
                onChange={(e) => setNewLeagueSlug(e.target.value)}
                placeholder="e.g. portugal_primeira"
                className="w-full px-4 py-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 dark:bg-slate-700 dark:text-gray-100 text-base font-mono"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Lowercase letters, digits, underscores. Spaces are auto-converted.
              </p>
            </div>
          )}

          <div>
            <label htmlFor="csv" className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
              CSV file
            </label>
            <input
              ref={fileInputRef}
              id="csv"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-gray-700 dark:text-gray-300 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-emerald-50 file:text-emerald-700 hover:file:bg-emerald-100 dark:file:bg-emerald-900/40 dark:file:text-emerald-300"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Required columns: <span className="font-mono">Date, HomeTeam, AwayTeam, FTHG, FTAG</span>.
            </p>
          </div>

          <button
            type="submit"
            disabled={uploading || !effectiveLeague || !file}
            className="inline-flex items-center justify-center gap-2 px-5 py-3 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-semibold shadow-md hover:shadow-lg transition-all disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploading ? "Uploading…" : "Upload CSV"}
          </button>
        </form>
      </section>

      {toast && (
        <div
          className={`mt-6 rounded-lg p-4 flex items-start gap-3 border ${
            toast.kind === "ok"
              ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800/40 text-emerald-800 dark:text-emerald-200"
              : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/40 text-red-800 dark:text-red-200"
          }`}
        >
          {toast.kind === "ok" ? (
            <CheckCircle2 className="h-5 w-5 mt-0.5 flex-shrink-0" />
          ) : (
            <AlertTriangle className="h-5 w-5 mt-0.5 flex-shrink-0" />
          )}
          <p className="text-sm">{toast.text}</p>
        </div>
      )}

      {/* Per-league CSV manager — sits between the upload form and the
          overview table so the typical "see what's there → delete the
          stale file → re-upload the fresh one" flow happens in a
          single vertical column. Renders nothing when the picker is on
          the "new league" sentinel. */}
      <LeagueCsvManager
        league={effectiveLeague}
        onChange={refreshLeagues}
      />

      {/* League table */}
      <section className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-50">
            Leagues
          </h2>
          <button
            onClick={refreshLeagues}
            disabled={overviewLoading}
            className="inline-flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50"
          >
            <RefreshCcw className={`h-4 w-4 ${overviewLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {overviewError && (
          <div className="rounded-lg p-4 border border-red-200 dark:border-red-800/40 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm mb-4">
            {overviewError}
          </div>
        )}

        <div className="overflow-hidden bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-slate-700 text-sm">
            <thead className="bg-gray-50 dark:bg-slate-900/40 text-gray-500 dark:text-gray-400 uppercase text-xs tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">League</th>
                <th className="px-4 py-3 text-right">CSVs</th>
                <th className="px-4 py-3 text-left">Last uploaded</th>
                <th className="px-4 py-3 text-left">Model</th>
                <th className="px-4 py-3 text-left">Last trained</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-700">
              {leagues.length === 0 && !overviewLoading && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    No leagues yet. Upload a CSV above to get started.
                  </td>
                </tr>
              )}
              {leagues.map((l) => (
                <tr key={l.league} className="hover:bg-gray-50/60 dark:hover:bg-slate-900/20">
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100 font-mono">
                    {l.league}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">{l.csv_count}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatDate(l.last_uploaded)}</td>
                  <td className="px-4 py-3">
                    {l.model_trained ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-xs font-medium">
                        <CheckCircle2 className="h-3 w-3" /> Ready
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300 text-xs font-medium">
                        Not trained
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                    {formatDate(l.model_last_trained)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleTrain(l.league)}
                      disabled={trainingLeague !== null || l.csv_count === 0}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                      title={l.csv_count === 0 ? "Upload a CSV first" : "Retrain model"}
                    >
                      {trainingLeague === l.league ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                      {trainingLeague === l.league ? "Training…" : l.model_trained ? "Retrain" : "Train"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">
          Training runs synchronously and can take 30s–2min depending on the dataset. Don't navigate
          away while a job is in flight.
        </p>
      </section>
    </div>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
