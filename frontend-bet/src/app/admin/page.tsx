"use client";

import React from 'react';
import Link from 'next/link';
import {
  Activity,
  AlertCircle,
  Crown,
  DollarSign,
  Loader2,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
  Users,
} from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';
import { useAdminInfo } from '@/hooks/useAdminInfo';
import {
  OddsApiDailyChart,
  SportBreakdownChart,
  UserRoleDonut,
} from '@/components/admin/AdminCharts';

export default function AdminPage() {
  const { customUserProfile, isLoadingAuth, firebaseUser } = useAuth();
  const role = customUserProfile?.role;

  // Auth gate: render messaging instead of fetching when the user isn't an
  // admin. We let the hook fire only after we know the role, so a non-admin
  // never even hits /admin/info (saves a guaranteed-403 round trip).
  const isAdmin = role === 'admin';

  if (isLoadingAuth) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-sky-500" />
      </div>
    );
  }

  if (!firebaseUser) {
    return (
      <PageShell>
        <NotAuthorized
          title="Sign in required"
          message="You need to be signed in as an admin to view this dashboard."
          ctaHref="/auth/login"
          ctaLabel="Go to sign in"
        />
      </PageShell>
    );
  }

  if (!isAdmin) {
    return (
      <PageShell>
        <NotAuthorized
          title="Admins only"
          message="This dashboard is restricted to admin accounts. If you think you should have access, contact the site owner."
          ctaHref="/dashboard"
          ctaLabel="Back to dashboard"
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <AdminDashboard />
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-gray-50 dark:bg-slate-950 font-sans min-h-screen">
      <div className="container mx-auto px-4 py-8 md:py-12 max-w-7xl">{children}</div>
    </div>
  );
}

function NotAuthorized({
  title,
  message,
  ctaHref,
  ctaLabel,
}: {
  title: string;
  message: string;
  ctaHref: string;
  ctaLabel: string;
}) {
  return (
    <div className="max-w-md mx-auto text-center py-24">
      <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 mb-5">
        <ShieldCheck className="h-7 w-7" />
      </div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50 mb-2">{title}</h1>
      <p className="text-gray-600 dark:text-gray-300 mb-6">{message}</p>
      <Link
        href={ctaHref}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md transition-all"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}

function AdminDashboard() {
  const { data, isLoading, isRefreshing, error, lastUpdated, refetch } = useAdminInfo();

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-sky-500" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="max-w-md mx-auto py-24 text-center">
        <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 mb-5">
          <AlertCircle className="h-7 w-7" />
        </div>
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-50 mb-2">
          Could not load admin info
        </h1>
        <p className="text-gray-600 dark:text-gray-300 mb-6">{error}</p>
        <button
          onClick={refetch}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-300 dark:border-slate-600 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors text-sm font-medium"
        >
          <RefreshCw className="h-4 w-4" />
          Try again
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <>
      {/* Header */}
      <header className="mb-8 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide bg-gradient-to-r from-amber-500 to-rose-500 text-white shadow-sm">
              <ShieldCheck className="h-3 w-3" />
              Admin
            </span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-50">
            Platform overview
          </h1>
          <p className="text-base text-gray-600 dark:text-gray-300 mt-2 max-w-2xl">
            Live dashboard for users, tracking load, and Odds API spend. Auto-refreshes every 30 seconds.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          <button
            onClick={refetch}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors text-sm font-medium disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 p-3 text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-lg">
          Refresh failed: {error}. Showing last successful snapshot.
        </div>
      )}

      {/* Key metric tiles */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricTile
          icon={<Users className="h-5 w-5" />}
          label="Total users"
          value={data.users.total}
          accent="sky"
          subline={`+${data.users.signups_last_7d} in last 7d`}
        />
        <MetricTile
          icon={<Crown className="h-5 w-5" />}
          label="Paying users"
          value={data.users.paying}
          accent="amber"
          subline={`${data.users.by_role.premium} on premium role`}
        />
        <MetricTile
          icon={<Activity className="h-5 w-5" />}
          label="Active trackers"
          value={data.tracking.active_trackers}
          accent="emerald"
          subline={`${data.tracking.total_matches_ever} tracked all-time`}
        />
        <MetricTile
          icon={<DollarSign className="h-5 w-5" />}
          label="Projected API calls / day"
          value={Math.round(data.tracking.projected_odds_api_calls_per_day)}
          accent="rose"
          subline={`${data.odds_api.calls_today ?? '—'} actual today`}
          highlight
        />
      </section>

      {/* Users + Tracking sport breakdown side-by-side */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <Card>
          <CardHeader
            icon={<Users className="h-5 w-5 text-sky-500" />}
            title="Users by role"
            subtitle={`${data.users.signups_last_30d} signups in last 30 days`}
          />
          <UserRoleDonut users={data.users} />
        </Card>
        <Card>
          <CardHeader
            icon={<TrendingUp className="h-5 w-5 text-emerald-500" />}
            title="Tracking by sport"
            subtitle="Lifetime totals vs currently-running trackers"
          />
          <SportBreakdownChart
            bySport={data.tracking.by_sport}
            activeBySport={data.tracking.active_by_sport}
          />
        </Card>
      </section>

      {/* Odds API spend */}
      <section className="mb-8">
        <Card>
          <CardHeader
            icon={<DollarSign className="h-5 w-5 text-rose-500" />}
            title="Odds API daily calls"
            subtitle={
              data.odds_api.configured
                ? `${data.odds_api.calls_total ?? 0} lifetime · ${data.odds_api.calls_today ?? 0} today`
                : 'ODDS_API_KEY not configured — counters inactive'
            }
          />
          {data.odds_api.daily_history.length > 0 ? (
            <OddsApiDailyChart history={data.odds_api.daily_history} />
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400 italic py-12 text-center">
              No call history yet.
            </p>
          )}
        </Card>
      </section>

      {/* Top users + diagnostic counts */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              icon={<Crown className="h-5 w-5 text-amber-500" />}
              title="Top active trackers per user"
              subtitle="Spot a single account driving most of the cost"
            />
            <TopUsersTable users={data.tracking.top_active_users} />
          </Card>
        </div>
        <Card>
          <CardHeader
            icon={<Activity className="h-5 w-5 text-indigo-500" />}
            title="System health"
            subtitle="Should agree with active_trackers"
          />
          <dl className="space-y-3 mt-4">
            <DiagnosticRow label="DB active rows" value={data.tracking.active_trackers} />
            <DiagnosticRow label="Redis index size" value={data.tracking.redis_index_size} />
            <DiagnosticRow label="Scheduler jobs" value={data.tracking.scheduler_job_count} />
            <DiagnosticRow label="Pending results" value={data.tracking.pending_match_results} />
            <DiagnosticRow label="Total snapshots" value={data.tracking.total_snapshots} />
            <DiagnosticRow
              label="Daily-track counters"
              value={data.redis.daily_track_counters_active}
            />
          </dl>
        </Card>
      </section>
    </>
  );
}

// ─── small presentational helpers ──────────────────────────────────────────

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6 shadow-sm">
      {children}
    </div>
  );
}

function CardHeader({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-start gap-3 mb-4">
      <div className="mt-0.5">{icon}</div>
      <div>
        <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100">{title}</h2>
        {subtitle && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{subtitle}</p>
        )}
      </div>
    </div>
  );
}

const ACCENT_CLASSES: Record<string, string> = {
  sky: 'from-sky-50 to-sky-100/40 dark:from-sky-900/20 dark:to-sky-900/5 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800/40',
  amber: 'from-amber-50 to-amber-100/40 dark:from-amber-900/20 dark:to-amber-900/5 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/40',
  emerald: 'from-emerald-50 to-emerald-100/40 dark:from-emerald-900/20 dark:to-emerald-900/5 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/40',
  rose: 'from-rose-50 to-rose-100/40 dark:from-rose-900/20 dark:to-rose-900/5 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/40',
};

function MetricTile({
  icon,
  label,
  value,
  subline,
  accent,
  highlight = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  subline?: string;
  accent: 'sky' | 'amber' | 'emerald' | 'rose';
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl p-4 sm:p-5 bg-gradient-to-br border ${ACCENT_CLASSES[accent]} ${
        highlight ? 'ring-2 ring-rose-300/60 dark:ring-rose-700/40' : ''
      }`}
    >
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide opacity-80">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-2xl sm:text-3xl font-bold text-gray-900 dark:text-gray-50">
        {value.toLocaleString()}
      </div>
      {subline && (
        <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{subline}</div>
      )}
    </div>
  );
}

function DiagnosticRow({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <dt className="text-gray-600 dark:text-gray-400">{label}</dt>
      <dd className="font-semibold text-gray-900 dark:text-gray-100">
        {value == null ? <span className="text-gray-400 dark:text-gray-500">—</span> : value.toLocaleString()}
      </dd>
    </div>
  );
}

function TopUsersTable({
  users,
}: {
  users: import('@/types/admin').AdminTopUser[];
}) {
  if (!users.length) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 italic py-6 text-center">
        No active trackers yet.
      </p>
    );
  }

  const roleClasses: Record<string, string> = {
    normal: 'bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-300',
    premium: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
    admin: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    unknown: 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-gray-400',
  };

  return (
    <div className="overflow-x-auto -mx-2 mt-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            <th className="px-2 py-2 font-medium">User</th>
            <th className="px-2 py-2 font-medium">Role</th>
            <th className="px-2 py-2 font-medium text-right">Active</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr
              key={u.user_id}
              className="border-t border-gray-100 dark:border-slate-700/60"
            >
              <td className="px-2 py-2.5 text-gray-800 dark:text-gray-100 truncate max-w-[260px]">
                {u.email || <span className="text-gray-400 italic">no email</span>}
              </td>
              <td className="px-2 py-2.5">
                <span
                  className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                    roleClasses[u.role] || roleClasses.unknown
                  }`}
                >
                  {u.role}
                </span>
              </td>
              <td className="px-2 py-2.5 text-right font-semibold text-gray-900 dark:text-gray-100 tabular-nums">
                {u.active_trackers}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
