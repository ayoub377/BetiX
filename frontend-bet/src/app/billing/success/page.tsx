"use client";

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCircle2, Loader2, AlertTriangle } from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';

// LemonSqueezy webhooks usually fire within ~1–3s of checkout completion.
// Poll for up to 30s, then fall back to a manual-refresh prompt.
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 30_000;

export default function BillingSuccessPage() {
  const router = useRouter();
  const { customUserProfile, refreshUserProfile, firebaseUser } = useAuth();
  const [phase, setPhase] = useState<'polling' | 'confirmed' | 'timeout'>('polling');

  // If the user landed here without being signed in (e.g. cleared cookies
  // mid-flow), bounce them back to login. The webhook will still have
  // updated their role server-side.
  useEffect(() => {
    if (firebaseUser === null) {
      // not loading and not authed
      router.replace('/auth/login?next=/dashboard');
    }
  }, [firebaseUser, router]);

  // If role is already premium/admin (e.g. the webhook beat the redirect),
  // skip straight to confirmed.
  useEffect(() => {
    const role = customUserProfile?.role;
    if (role === 'premium' || role === 'admin') {
      setPhase('confirmed');
    }
  }, [customUserProfile?.role]);

  // Poll /api/users/me until role flips to premium, or we time out.
  useEffect(() => {
    if (phase !== 'polling' || !firebaseUser) return;

    const startedAt = Date.now();
    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      try {
        await refreshUserProfile();
      } catch (err) {
        console.error('Failed to refresh profile:', err);
      }
      if (cancelled) return;
      if (Date.now() - startedAt >= POLL_TIMEOUT_MS) {
        setPhase((p) => (p === 'polling' ? 'timeout' : p));
      }
    };

    const interval = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [phase, firebaseUser, refreshUserProfile]);

  // Auto-redirect to the dashboard once confirmed.
  useEffect(() => {
    if (phase === 'confirmed') {
      const t = setTimeout(() => router.replace('/dashboard'), 2000);
      return () => clearTimeout(t);
    }
  }, [phase, router]);

  return (
    <div className="flex flex-col min-h-screen bg-gray-100 dark:bg-slate-900 items-center justify-center p-6">
      <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl max-w-md w-full p-8 text-center">
        {phase === 'polling' && (
          <>
            <Loader2 className="h-12 w-12 mx-auto mb-4 text-sky-500 animate-spin" />
            <h1 className="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
              Activating your subscription...
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Payment received. We're waiting for our billing provider to
              confirm — usually just a couple of seconds.
            </p>
          </>
        )}

        {phase === 'confirmed' && (
          <>
            <CheckCircle2 className="h-12 w-12 mx-auto mb-4 text-emerald-500" />
            <h1 className="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
              Welcome to Premium!
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              You now have access to expanded quotas and faster polling.
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              Redirecting to your dashboard...
            </p>
          </>
        )}

        {phase === 'timeout' && (
          <>
            <AlertTriangle className="h-12 w-12 mx-auto mb-4 text-amber-500" />
            <h1 className="text-2xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
              Still waiting on confirmation
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Your payment went through but our system hasn't received the
              confirmation yet. This is usually temporary — refresh in a
              minute, or contact support if it persists.
            </p>
            <button
              onClick={() => router.replace('/dashboard')}
              className="w-full py-2.5 px-4 rounded-lg bg-sky-500 hover:bg-sky-600 text-white font-medium"
            >
              Continue to dashboard
            </button>
          </>
        )}
      </div>
    </div>
  );
}
