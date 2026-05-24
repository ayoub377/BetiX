"use client";

import React, { useState } from "react";
import {
  AlertTriangle,
  FileText,
  Loader2,
  RefreshCcw,
  Trash2,
} from "lucide-react";

import { useLeagueCsvs, type LeagueCsvFile } from "@/hooks/useLeagueCsvs";

interface LeagueCsvManagerProps {
  /** League slug as understood by the backend, or empty / sentinel
   *  ("__new__") when the admin hasn't selected a real league yet. */
  league: string;
  /** Called after a successful delete so the parent can refresh the
   *  leagues overview (CSV counts, last-uploaded timestamp). */
  onChange?: () => void;
}

/**
 * Lists the CSVs currently stored for ``league`` and offers a per-row
 * delete. Two-click confirmation (Delete → Confirm) avoids browser
 * ``confirm()`` dialogs without needing a full modal system.
 *
 * Renders nothing when no concrete league is selected — keeps the page
 * tidy while the admin types a new slug.
 */
export default function LeagueCsvManager({ league, onChange }: LeagueCsvManagerProps) {
  const { files, isLoading, error, refresh, deleteFile } = useLeagueCsvs(league);
  // `confirmFor` holds the filename whose delete button is in
  // "are you sure" mode. We only allow one confirmation at a time so a
  // distracted admin can't queue several deletes by mistake.
  const [confirmFor, setConfirmFor] = useState<string | null>(null);
  const [deletingFile, setDeletingFile] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Don't render anything when there's no league context — the upload
  // form's picker handles that messaging.
  if (!league || league.startsWith("__")) {
    return null;
  }

  const handleDelete = async (filename: string) => {
    setDeletingFile(filename);
    setDeleteError(null);
    try {
      await deleteFile(filename);
      onChange?.();
    } catch (err) {
      console.error("Delete failed:", err);
      setDeleteError(
        `Could not delete ${filename}. The file may already be gone or the server may be down.`,
      );
    } finally {
      setDeletingFile(null);
      setConfirmFor(null);
    }
  };

  return (
    <section className="mt-8 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-700 p-6 md:p-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-50">
          <FileText className="h-5 w-5 text-emerald-500" />
          Stored CSVs for{" "}
          <span className="font-mono text-base text-gray-700 dark:text-gray-300">
            {league}
          </span>
        </h2>
        <button
          onClick={refresh}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50"
          aria-label="Refresh CSV list"
        >
          <RefreshCcw
            className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
        Re-uploading a file with the same name overwrites in place. Use delete
        when the filename has changed (e.g. last season's snapshot left over,
        or a renamed weekly drop) so the trainer doesn't double-count rows.
      </p>

      {error && (
        <div className="mb-4 rounded-lg p-3 border border-red-200 dark:border-red-800/40 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm">
          {error}
        </div>
      )}

      {deleteError && (
        <div className="mb-4 rounded-lg p-3 border border-red-200 dark:border-red-800/40 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          {deleteError}
        </div>
      )}

      {isLoading && files.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-gray-500 dark:text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : files.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
          No CSVs uploaded for this league yet.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-slate-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-slate-700 text-sm">
            <thead className="bg-gray-50 dark:bg-slate-900/40 text-gray-500 dark:text-gray-400 uppercase text-xs tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">Filename</th>
                <th className="px-4 py-2.5 text-right">Size</th>
                <th className="px-4 py-2.5 text-left">Last modified</th>
                <th className="px-4 py-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-700">
              {files.map((f) => (
                <FileRow
                  key={f.filename}
                  file={f}
                  isConfirming={confirmFor === f.filename}
                  isDeleting={deletingFile === f.filename}
                  // Only allow opening a new confirm when no delete is
                  // in flight — protects the optimistic state in the hook.
                  onAskConfirm={() =>
                    deletingFile === null && setConfirmFor(f.filename)
                  }
                  onCancelConfirm={() => setConfirmFor(null)}
                  onConfirm={() => handleDelete(f.filename)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface FileRowProps {
  file: LeagueCsvFile;
  isConfirming: boolean;
  isDeleting: boolean;
  onAskConfirm: () => void;
  onCancelConfirm: () => void;
  onConfirm: () => void;
}

function FileRow({
  file,
  isConfirming,
  isDeleting,
  onAskConfirm,
  onCancelConfirm,
  onConfirm,
}: FileRowProps) {
  return (
    <tr className="hover:bg-gray-50/60 dark:hover:bg-slate-900/20">
      <td className="px-4 py-2.5 font-mono text-gray-900 dark:text-gray-100 break-all">
        {file.filename}
      </td>
      <td className="px-4 py-2.5 text-right text-gray-600 dark:text-gray-400 tabular-nums">
        {formatBytes(file.size_bytes)}
      </td>
      <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
        {formatDate(file.last_modified)}
      </td>
      <td className="px-4 py-2.5 text-right">
        {isConfirming ? (
          <div className="inline-flex items-center gap-1.5">
            <button
              onClick={onConfirm}
              disabled={isDeleting}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-red-600 hover:bg-red-700 text-white text-xs font-medium disabled:opacity-50"
            >
              {isDeleting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              {isDeleting ? "Deleting…" : "Confirm"}
            </button>
            <button
              onClick={onCancelConfirm}
              disabled={isDeleting}
              className="px-2.5 py-1 rounded-md border border-gray-300 dark:border-slate-600 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={onAskConfirm}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-red-300 dark:border-red-800/40 text-red-700 dark:text-red-300 text-xs font-medium hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </button>
        )}
      </td>
    </tr>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
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
