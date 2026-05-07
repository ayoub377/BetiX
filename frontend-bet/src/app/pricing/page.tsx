"use client";

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, Zap, Loader2 } from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';
import { apiClient, isApiError } from '@/lib/apiClient';

const PREMIUM_FEATURES = [
  '100 daily team comparisons (vs. 5 on Free)',
  '100 daily Dixon-Coles predictions (vs. 5 on Free)',
  '10 concurrent match trackers (vs. 1 on Free)',
  '10 new tracks per day (vs. 1 on Free)',
  'Faster odds polling: every 10 minutes (vs. 45 on Free)',
  'Track matches up to 48 hours before kickoff (vs. 12 on Free)',
];

export default function PricingPage() {
  const router = useRouter();
  const { firebaseUser, customUserProfile, isLoadingAuth } = useAuth();
  const [isCreatingCheckout, setIsCreatingCheckout] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const role = customUserProfile?.role ?? 'normal';
  const isAlreadyPremium = role === 'premium' || role === 'admin';

  const handleSubscribe = async () => {
    if (!firebaseUser) {
      router.push('/auth/login?next=/pricing');
      return;
    }
    setIsCreatingCheckout(true);
    setError(null);
    try {
      const res = await apiClient.post<{ url: string }>('/billing/checkout');
      window.location.assign(res.data.url);
    } catch (err) {
      console.error('Checkout failed:', err);
      if (isApiError(err) && err.response) {
        const detail = (err.response.data as { detail?: string })?.detail;
        setError(detail ?? 'Could not start checkout. Please try again.');
      } else {
        setError('Could not start checkout. Please try again.');
      }
      setIsCreatingCheckout(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-gray-100 dark:bg-slate-900 font-sans">
      <main className="flex-grow container mx-auto px-4 py-12 md:py-16 max-w-5xl">
        <header className="text-center mb-12">
          <h1 className="text-4xl sm:text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-sky-500 to-emerald-500 dark:from-blue-400 dark:via-sky-400 dark:to-emerald-300 pb-2">
            Pricing
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-300 mt-3 max-w-xl mx-auto">
            Start free. Upgrade when you need more requests, more concurrent
            trackers, or finer-grained odds polling.
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-3xl mx-auto">
          {/* Free tier card */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl p-8 shadow-lg border border-gray-200 dark:border-slate-700 flex flex-col">
            <h2 className="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
              Free
            </h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              For trying out the platform.
            </p>
            <p className="mb-6">
              <span className="text-4xl font-bold text-gray-800 dark:text-gray-100">
                $0
              </span>
              <span className="text-gray-500 dark:text-gray-400 ml-1">/ month</span>
            </p>
            <ul className="space-y-2 mb-8 text-sm text-gray-700 dark:text-gray-300 flex-grow">
              <li className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                <span>5 daily comparisons</span>
              </li>
              <li className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                <span>5 daily predictions</span>
              </li>
              <li className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                <span>1 concurrent tracker</span>
              </li>
              <li className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                <span>Polling every 45 minutes</span>
              </li>
              <li className="flex items-start gap-2">
                <Check className="h-4 w-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                <span>Tracking up to 12h before kickoff</span>
              </li>
            </ul>
            <button
              disabled
              className="mt-auto w-full py-3 px-4 rounded-lg bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400 font-medium cursor-not-allowed"
            >
              Current plan
            </button>
          </div>

          {/* Premium tier card */}
          <div className="bg-gradient-to-br from-white to-sky-50 dark:from-slate-800 dark:to-sky-900/20 rounded-2xl p-8 shadow-2xl border-2 border-sky-500/40 dark:border-sky-400/40 flex flex-col relative">
            <div className="absolute -top-3 right-6 px-3 py-1 bg-gradient-to-r from-sky-500 to-emerald-500 text-white text-xs font-semibold rounded-full shadow-md">
              RECOMMENDED
            </div>
            <h2 className="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2 flex items-center gap-2">
              <Zap className="h-6 w-6 text-sky-500 dark:text-sky-400" />
              Premium
            </h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              For serious bettors who track multiple matches.
            </p>
            <p className="mb-6">
              <span className="text-4xl font-bold text-gray-800 dark:text-gray-100">
                $19
              </span>
              <span className="text-gray-500 dark:text-gray-400 ml-1">/ month</span>
            </p>
            <ul className="space-y-2 mb-8 text-sm text-gray-700 dark:text-gray-300 flex-grow">
              {PREMIUM_FEATURES.map((feature) => (
                <li key={feature} className="flex items-start gap-2">
                  <Check className="h-4 w-4 mt-0.5 text-sky-500 dark:text-sky-400 flex-shrink-0" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
            <button
              onClick={handleSubscribe}
              disabled={isCreatingCheckout || isLoadingAuth || isAlreadyPremium}
              className="mt-auto w-full py-3 px-4 rounded-lg bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {isCreatingCheckout ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Redirecting to checkout...
                </>
              ) : isAlreadyPremium ? (
                role === 'admin' ? 'Admin (full access)' : 'You are Premium'
              ) : firebaseUser ? (
                'Get Premium'
              ) : (
                'Sign in to subscribe'
              )}
            </button>
            {error && (
              <p className="mt-3 text-sm text-center text-red-600 dark:text-red-400">
                {error}
              </p>
            )}
            <p className="mt-3 text-xs text-center text-gray-500 dark:text-gray-400">
              Cancel anytime from your billing portal.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
