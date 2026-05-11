"use client";

import React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Brain,
  Sparkles,
  Trophy,
  Zap,
} from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import Button from "@/components/ui/Button";

const FEATURES = [
  {
    href: "/track",
    icon: Activity,
    title: "Live Odds Tracking",
    description:
      "Pin a match and watch odds drift in real time. We snapshot every 10 minutes on Premium, every 45 on Free.",
    accent: "from-sky-500 to-blue-600",
  },
  {
    href: "/predictions",
    icon: Brain,
    title: "Match Predictions",
    description:
      "Dixon-Coles statistical model trained on historical league data. Outcome probabilities for any fixture.",
    accent: "from-emerald-500 to-teal-600",
  },
  {
    href: "/pro-analysis",
    icon: Trophy,
    title: "Lineup Comparison",
    description:
      "Side-by-side player comparison by position. Spot value where the market is mispricing squad strength.",
    accent: "from-amber-500 to-orange-600",
  },
];

const FAQS = [
  {
    q: "How accurate are the Dixon-Coles predictions?",
    a: "The model is trained on multiple seasons of league results. It's a statistical baseline — useful for spotting outliers in market odds, not a magic crystal ball. Use it alongside our odds tracker.",
  },
  {
    q: "What's the difference between Free and Premium?",
    a: "Free gives you 5 daily comparisons, 5 predictions, 1 concurrent tracker, polling every 45 minutes, and tracking up to 12 hours before kickoff. Premium scales these to 100, 100, 10 concurrent, 10-minute polling, and 48-hour kickoff windows. See the pricing page for the full table.",
  },
  {
    q: "Where does the odds data come from?",
    a: "We poll FlashScore for the live consensus odds and cross-reference with Pinnacle's sharp lines via The Odds API. Tracking runs server-side in Redis + Postgres so your data persists even if you close the browser.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes — manage billing through the LemonSqueezy customer portal directly from your dashboard. No long-term contract, no hidden fees.",
  },
];

export default function HomePage() {
  const { firebaseUser, customUserProfile } = useAuth();
  const isSignedIn = !!firebaseUser;
  const role = customUserProfile?.role;

  return (
    <div className="bg-white dark:bg-slate-950">
      {/* ─── Hero ──────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 -z-10 bg-gradient-to-br from-blue-50 via-white to-emerald-50 dark:from-sky-950/40 dark:via-slate-950 dark:to-emerald-950/40" />
        <div className="absolute inset-0 -z-10 opacity-30 [mask-image:radial-gradient(ellipse_at_center,black_0%,transparent_70%)]">
          <div className="absolute -top-40 left-1/2 -translate-x-1/2 h-[600px] w-[1100px] bg-gradient-to-r from-sky-300 via-blue-400 to-indigo-400 dark:from-sky-700 dark:via-blue-700 dark:to-indigo-800 blur-3xl" />
        </div>

        <div className="container mx-auto px-4 py-20 md:py-28 lg:py-32 max-w-6xl">
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/80 dark:bg-slate-800/80 border border-gray-200 dark:border-slate-700 text-xs font-medium text-gray-700 dark:text-gray-300 mb-6 shadow-sm">
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              Built for serious bettors, not weekend tipsters
            </div>
            <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight text-gray-900 dark:text-gray-50">
              Sharper bets,{" "}
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-sky-500 via-blue-600 to-indigo-600">
                backed by data
              </span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-gray-600 dark:text-gray-300 max-w-2xl mx-auto leading-relaxed">
              Live odds tracking, statistical match predictions, lineup comparison, and arbitrage
              discovery — one platform, no Excel, no scraping spreadsheets.
            </p>
            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              {isSignedIn ? (
                <>
                  <Link
                    href="/dashboard"
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-lg hover:shadow-xl transition-all duration-200 text-base"
                  >
                    Go to dashboard
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  {role !== "premium" && role !== "admin" && (
                    <Link
                      href="/pricing"
                      className="inline-flex items-center gap-2 px-6 py-3 rounded-lg border-2 border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-200 hover:border-sky-500 dark:hover:border-sky-400 hover:bg-gray-50 dark:hover:bg-slate-800 font-semibold text-base transition-colors"
                    >
                      <Zap className="h-4 w-4 text-amber-500" />
                      See Premium
                    </Link>
                  )}
                </>
              ) : (
                <>
                  <Link
                    href="/auth/login"
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-lg hover:shadow-xl transition-all duration-200 text-base"
                  >
                    Get started — free
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Link
                    href="/pricing"
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-lg border-2 border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-200 hover:border-sky-500 dark:hover:border-sky-400 hover:bg-gray-50 dark:hover:bg-slate-800 font-semibold text-base transition-colors"
                  >
                    See pricing
                  </Link>
                </>
              )}
            </div>
            <p className="mt-6 text-xs text-gray-500 dark:text-gray-400">
              No credit card to start • Free tier always available • Cancel Premium anytime
            </p>
          </div>
        </div>
      </section>

      {/* ─── Features ──────────────────────────────────────────────── */}
      <section id="services" className="py-16 sm:py-20 lg:py-24">
        <div className="container mx-auto px-4 max-w-6xl">
          <div className="text-center mb-12 lg:mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-50">
              Four tools, one workflow
            </h2>
            <p className="mt-4 text-lg text-gray-600 dark:text-gray-300 max-w-2xl mx-auto">
              From spotting a market mispricing to confirming it with statistics — everything you
              need on the same page.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8">
            {FEATURES.map((feature) => {
              const Icon = feature.icon;
              return (
                <Link
                  key={feature.href}
                  href={feature.href}
                  className="group relative p-6 lg:p-8 rounded-2xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 hover:border-transparent hover:shadow-xl transition-all duration-300"
                >
                  <div
                    className={`inline-flex items-center justify-center h-12 w-12 rounded-xl bg-gradient-to-br ${feature.accent} text-white mb-4 shadow-md group-hover:scale-110 transition-transform`}
                  >
                    <Icon className="h-6 w-6" />
                  </div>
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-50 mb-2 flex items-center gap-2">
                    {feature.title}
                    <ArrowRight className="h-4 w-4 text-gray-400 group-hover:text-sky-500 group-hover:translate-x-1 transition-all" />
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                    {feature.description}
                  </p>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* ─── How it works ──────────────────────────────────────────── */}
      <section className="py-16 sm:py-20 bg-gray-50 dark:bg-slate-900/50">
        <div className="container mx-auto px-4 max-w-5xl">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 lg:gap-12">
            {[
              { step: "1", icon: BarChart3, title: "Pin a match", body: "Search by team or player. We start tracking live odds the moment you do." },
              { step: "2", icon: Brain, title: "See the signal", body: "Compare market odds against Dixon-Coles predictions and sharp Pinnacle lines." },
              { step: "3", icon: Trophy, title: "Place the bet", body: "Use the arbitrage scanner to lock in the best price across your books." },
            ].map(({ step, icon: Icon, title, body }) => (
              <div key={step} className="text-center">
                <div className="inline-flex items-center justify-center h-14 w-14 rounded-full bg-white dark:bg-slate-800 border-2 border-sky-500 dark:border-sky-400 text-sky-600 dark:text-sky-400 font-bold text-lg mb-4 shadow-sm">
                  {step}
                </div>
                <Icon className="h-6 w-6 mx-auto text-gray-400 dark:text-gray-500 mb-3" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-2">{title}</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── About ─────────────────────────────────────────────────── */}
      <section id="about" className="py-16 sm:py-20">
        <div className="container mx-auto px-4 max-w-4xl text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-50 mb-6">
            Built by bettors, for bettors
          </h2>
          <p className="text-lg text-gray-600 dark:text-gray-300 leading-relaxed">
            Sharper Bets started as a side project to scratch our own itch: too many tools across
            too many tabs. We pulled the four pieces of the analysis workflow into one place,
            wired them up with statistical models and live data feeds, and shipped it. No fluff,
            no "AI-powered" marketing copy — just the tools we wished existed.
          </p>
        </div>
      </section>

      {/* ─── FAQ ───────────────────────────────────────────────────── */}
      <section id="faq" className="py-16 sm:py-20 bg-gray-50 dark:bg-slate-900/50">
        <div className="container mx-auto px-4 max-w-3xl">
          <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-50 text-center mb-10">
            Frequently asked
          </h2>
          <div className="space-y-4">
            {FAQS.map((f) => (
              <details
                key={f.q}
                className="group bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden"
              >
                <summary className="flex items-center justify-between cursor-pointer px-6 py-5 hover:bg-gray-50 dark:hover:bg-slate-700/50 transition-colors">
                  <span className="font-medium text-gray-900 dark:text-gray-50">{f.q}</span>
                  <ArrowRight className="h-4 w-4 text-gray-400 group-open:rotate-90 transition-transform" />
                </summary>
                <div className="px-6 pb-5 text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                  {f.a}
                </div>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Final CTA ─────────────────────────────────────────────── */}
      {!isSignedIn && (
        <section className="py-16 sm:py-20">
          <div className="container mx-auto px-4 max-w-4xl text-center">
            <div className="rounded-3xl bg-gradient-to-br from-sky-500 to-indigo-600 p-10 sm:p-14 shadow-2xl">
              <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
                Ready to bet smarter?
              </h2>
              <p className="text-sky-50 max-w-xl mx-auto mb-8">
                Sign up free in 30 seconds. Upgrade to Premium when you need more.
              </p>
              <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                <Button
                  variant="secondary"
                  size="lg"
                  onClick={() => (window.location.href = "/auth/login")}
                  rightIcon={<ArrowRight className="h-4 w-4" />}
                  className="!bg-white !text-blue-700 hover:!bg-gray-100"
                >
                  Get started free
                </Button>
                <Link
                  href="/pricing"
                  className="px-6 py-3 rounded-md border-2 border-white/40 hover:border-white/80 text-white font-semibold transition-colors"
                >
                  See pricing
                </Link>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
