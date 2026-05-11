// src/app/dashboard/page.tsx
"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Brain,
  CreditCard,
  Loader2,
  LogOut,
  ShieldCheck,
  Sparkles,
  Trophy,
  Zap,
} from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { apiClient, isApiError } from "@/lib/apiClient";
import LogoutButton from "@/components/ui/LogoutButton";

const QUICK_ACTIONS = [
  {
    href: "/track",
    icon: Activity,
    title: "Track a match",
    description: "Pin a fixture and watch its odds drift in real time.",
    accent: "from-sky-500 to-indigo-600",
    iconBg: "bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400",
  },
  {
    href: "/predictions",
    icon: Brain,
    title: "Predict an outcome",
    description: "Dixon-Coles probabilities for any fixture.",
    accent: "from-emerald-500 to-teal-600",
    iconBg: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400",
  },
  {
    href: "/pro-analysis",
    icon: Trophy,
    title: "Compare lineups",
    description: "Side-by-side player comparison by position.",
    accent: "from-amber-500 to-orange-600",
    iconBg: "bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400",
  },
];

export default function DashboardPage() {
  const router = useRouter();
  const { firebaseUser, customUserProfile, isLoadingAuth } = useAuth();
  const [isOpeningPortal, setIsOpeningPortal] = useState(false);
  const [billingError, setBillingError] = useState<string | null>(null);

  // Redirect when not authed
  useEffect(() => {
    if (!isLoadingAuth && !firebaseUser) {
      router.push("/auth/login");
    }
  }, [isLoadingAuth, firebaseUser, router]);

  const role = customUserProfile?.role ?? "normal";
  const isPremium = role === "premium";
  const isAdmin = role === "admin";
  const quotas = customUserProfile?.quotas;

  const handleManageBilling = async () => {
    setIsOpeningPortal(true);
    setBillingError(null);
    try {
      const res = await apiClient.post<{ url: string }>("/billing/portal");
      window.location.assign(res.data.url);
    } catch (err) {
      console.error("Portal open failed:", err);
      if (isApiError(err) && err.response) {
        const detail = (err.response.data as { detail?: string })?.detail;
        setBillingError(detail ?? "Could not open billing portal.");
      } else {
        setBillingError("Could not open billing portal.");
      }
      setIsOpeningPortal(false);
    }
  };

  if (isLoadingAuth || (firebaseUser && !customUserProfile)) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-10 w-10 animate-spin text-sky-500" />
      </div>
    );
  }

  if (!firebaseUser) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] text-gray-500 dark:text-gray-400">
        Redirecting to login…
      </div>
    );
  }

  const userName =
    customUserProfile?.displayName?.split(" ")[0] ||
    firebaseUser.displayName?.split(" ")[0] ||
    firebaseUser.email?.split("@")[0] ||
    "there";

  const formatLimit = (n: number | undefined) =>
    n === undefined ? "—" : n === -1 ? "Unlimited" : `${n}`;

  return (
    <div className="container mx-auto px-4 py-8 md:py-12 max-w-6xl space-y-8">
      {/* ─── Hero greeting ──────────────────────────────────────── */}
      <section className="bg-gradient-to-br from-white to-sky-50 dark:from-slate-800 dark:to-sky-950/30 border border-gray-200 dark:border-slate-700 rounded-2xl p-6 md:p-8 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Welcome back</p>
            <h1 className="text-2xl md:text-3xl font-bold text-gray-900 dark:text-gray-50 flex items-center gap-3">
              {userName}
              <RolePill role={role} />
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mt-2 max-w-lg">
              {isAdmin
                ? "Full operational access — every endpoint, no quotas."
                : isPremium
                ? "Thanks for being Premium. Your quotas and faster polling are active."
                : "You're on the Free tier. Upgrade anytime for more daily requests and faster polling."}
            </p>
          </div>
          {!isPremium && !isAdmin && (
            <Link
              href="/pricing"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200"
            >
              <Zap className="h-4 w-4" />
              Upgrade to Premium
            </Link>
          )}
        </div>
      </section>

      {/* ─── Quick actions ──────────────────────────────────────── */}
      <section>
        <h2 className="text-xs font-semibold tracking-wider uppercase text-gray-500 dark:text-gray-400 mb-3">
          Quick actions
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {QUICK_ACTIONS.map((action) => {
            const Icon = action.icon;
            return (
              <Link
                key={action.href}
                href={action.href}
                className="group relative bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6 hover:border-transparent hover:shadow-xl transition-all duration-300 overflow-hidden"
              >
                <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${action.accent}`} />
                <div className={`inline-flex h-11 w-11 rounded-xl items-center justify-center mb-4 ${action.iconBg}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="font-semibold text-gray-900 dark:text-gray-50 mb-1 flex items-center gap-2">
                  {action.title}
                  <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-sky-500 group-hover:translate-x-1 transition-all" />
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                  {action.description}
                </p>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ─── Plan + Limits grid ─────────────────────────────────── */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Plan card */}
        <div className="lg:col-span-1 bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold tracking-wider uppercase text-gray-500 dark:text-gray-400">
              Your plan
            </h2>
            <RolePill role={role} compact />
          </div>
          <div className="flex-1">
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-50 mb-1">
              {isAdmin ? "Admin" : isPremium ? "Premium" : "Free"}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              {isAdmin
                ? "Operational access"
                : isPremium
                ? "$19 / month"
                : "Always free"}
            </p>
          </div>
          {isPremium && (
            <>
              <button
                onClick={handleManageBilling}
                disabled={isOpeningPortal}
                className="w-full py-2.5 px-4 rounded-lg border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-slate-700 text-sm font-medium transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              >
                <CreditCard className="h-4 w-4" />
                {isOpeningPortal ? "Opening portal…" : "Manage billing"}
              </button>
              {billingError && (
                <p className="mt-2 text-xs text-red-600 dark:text-red-400">{billingError}</p>
              )}
            </>
          )}
          {!isPremium && !isAdmin && (
            <Link
              href="/pricing"
              className="w-full py-2.5 px-4 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-sm hover:shadow-md transition-all"
            >
              <Zap className="h-4 w-4" />
              Upgrade
            </Link>
          )}
        </div>

        {/* Limits grid */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6">
          <h2 className="text-xs font-semibold tracking-wider uppercase text-gray-500 dark:text-gray-400 mb-4">
            Your limits
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <LimitStat
              icon={<Trophy className="h-4 w-4" />}
              label="Daily comparisons"
              value={formatLimit(quotas?.daily_compare_limit)}
            />
            <LimitStat
              icon={<Brain className="h-4 w-4" />}
              label="Daily predictions"
              value={formatLimit(quotas?.daily_predict_limit)}
            />
            <LimitStat
              icon={<Activity className="h-4 w-4" />}
              label="Daily new tracks"
              value={formatLimit(quotas?.daily_track_limit)}
            />
            <LimitStat
              icon={<BarChart3 className="h-4 w-4" />}
              label="Concurrent trackers"
              value={formatLimit(quotas?.concurrent_tracker_limit)}
            />
            <LimitStat
              icon={<Sparkles className="h-4 w-4" />}
              label="Poll cadence"
              value={
                quotas
                  ? `${Math.round(quotas.track_poll_interval_seconds / 60)} min`
                  : "—"
              }
            />
            <LimitStat
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Kickoff window"
              value={
                quotas
                  ? quotas.track_kickoff_lookahead_seconds === -1
                    ? "Unlimited"
                    : `${Math.round(quotas.track_kickoff_lookahead_seconds / 3600)}h`
                  : "—"
              }
            />
          </div>
        </div>
      </section>

      {/* ─── Account ────────────────────────────────────────────── */}
      <section className="bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6">
        <h2 className="text-xs font-semibold tracking-wider uppercase text-gray-500 dark:text-gray-400 mb-4">
          Account
        </h2>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm text-gray-500 dark:text-gray-400">Signed in as</p>
            <p className="font-medium text-gray-900 dark:text-gray-50 truncate">
              {firebaseUser.email}
            </p>
          </div>
          <LogoutButton
            showText
            text="Sign out"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
            iconClassName="h-4 w-4"
          />
        </div>
      </section>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────

function RolePill({ role, compact }: { role: "normal" | "premium" | "admin"; compact?: boolean }) {
  const config: Record<typeof role, { label: string; icon: React.ReactNode; className: string }> = {
    normal: {
      label: "Free",
      icon: null,
      className: "bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-300 border border-gray-200 dark:border-slate-600",
    },
    premium: {
      label: "Premium",
      icon: <Sparkles className="h-3 w-3" />,
      className: "bg-gradient-to-r from-sky-500 to-indigo-600 text-white",
    },
    admin: {
      label: "Admin",
      icon: <ShieldCheck className="h-3 w-3" />,
      className: "bg-gradient-to-r from-amber-500 to-rose-500 text-white",
    },
  };
  const c = config[role];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-semibold ${
        compact ? "text-[10px]" : "text-xs"
      } ${c.className}`}
    >
      {c.icon}
      {c.label}
    </span>
  );
}

function LimitStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-gray-50 dark:bg-slate-700/40 border border-gray-100 dark:border-slate-700">
      <div className="flex-shrink-0 h-8 w-8 rounded-md bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-600 flex items-center justify-center text-gray-500 dark:text-gray-400">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</div>
        <div className="text-sm font-semibold text-gray-900 dark:text-gray-50 truncate">
          {value}
        </div>
      </div>
    </div>
  );
}
