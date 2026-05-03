// src/contexts/AuthContext.tsx
"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { onAuthStateChanged, User as FirebaseUser } from 'firebase/auth';
import { auth as firebaseAuthInstance } from '@/lib/firebaseConfig';
import { apiClient, isApiError } from '@/lib/apiClient';

export type UserRole = 'normal' | 'premium' | 'admin';

export interface UserQuotas {
  daily_predict_limit: number;
  daily_compare_limit: number;
  daily_track_limit: number;
  concurrent_tracker_limit: number;
  track_poll_interval_seconds: number;
  track_kickoff_lookahead_seconds: number;
}

export interface CustomUserProfile {
  uid: string;
  email: string | null;
  displayName: string | null;
  role: UserRole;
  isPremiumMember: boolean; // derived: role === 'premium' || role === 'admin'
  subscriptionStatus: string | null;
  currentPeriodEnd: string | null;
  quotas: UserQuotas;
  // Client-side placeholder until PR2 surfaces real backend counters.
  requestsMadeToday: number;
  nextQuotaResetAt: number;
}

export interface AuthContextType {
  firebaseUser: FirebaseUser | null;
  customUserProfile: CustomUserProfile | null;
  isLoadingAuth: boolean;
  canMakeRequest: boolean;
  requestsLeftToday: number;
  nextQuotaResetTimeDisplay: string | null;
  recordSuccessfulRequest: () => Promise<void>;
  refreshUserProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface MeResponse {
  id: string;
  firebase_uid: string;
  email: string | null;
  role: UserRole;
  subscription_status: string | null;
  current_period_end: string | null;
  quotas: UserQuotas;
}

const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;

function localCounterKey(uid: string): string {
  return `requestsMadeToday_${uid}`;
}

function readLocalCounter(uid: string): { requestsMadeToday: number; nextQuotaResetAt: number } {
  try {
    const raw = localStorage.getItem(localCounterKey(uid));
    if (raw) {
      const parsed = JSON.parse(raw) as { requestsMadeToday?: number; nextQuotaResetAt?: number };
      if (parsed.nextQuotaResetAt && Date.now() < parsed.nextQuotaResetAt) {
        return {
          requestsMadeToday: parsed.requestsMadeToday ?? 0,
          nextQuotaResetAt: parsed.nextQuotaResetAt,
        };
      }
    }
  } catch (e) {
    console.warn('AuthContext: failed to read local counter', e);
  }
  return { requestsMadeToday: 0, nextQuotaResetAt: Date.now() + TWENTY_FOUR_HOURS_MS };
}

function writeLocalCounter(uid: string, value: { requestsMadeToday: number; nextQuotaResetAt: number }) {
  try {
    localStorage.setItem(localCounterKey(uid), JSON.stringify(value));
  } catch (e) {
    console.warn('AuthContext: failed to write local counter', e);
  }
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [customUserProfile, setCustomUserProfile] = useState<CustomUserProfile | null>(null);
  const [isLoadingAuth, setIsLoadingAuth] = useState(true);

  const fetchOrRefreshCustomProfile = async (user: FirebaseUser | null) => {
    if (!user) {
      setCustomUserProfile(null);
      setIsLoadingAuth(false);
      return;
    }

    try {
      const response = await apiClient.get<MeResponse>('/users/me');
      const me = response.data;
      const isPremium = me.role === 'premium' || me.role === 'admin';
      const counter = readLocalCounter(user.uid);

      setCustomUserProfile({
        uid: me.firebase_uid,
        email: me.email ?? user.email,
        displayName: user.displayName,
        role: me.role,
        isPremiumMember: isPremium,
        subscriptionStatus: me.subscription_status,
        currentPeriodEnd: me.current_period_end,
        quotas: me.quotas,
        requestsMadeToday: counter.requestsMadeToday,
        nextQuotaResetAt: counter.nextQuotaResetAt,
      });
    } catch (err) {
      if (isApiError(err)) {
        console.error('AuthContext: /users/me failed', err.response?.status, err.response?.data);
      } else {
        console.error('AuthContext: /users/me unexpected error', err);
      }
      setCustomUserProfile(null);
    } finally {
      setIsLoadingAuth(false);
    }
  };

  useEffect(() => {
    if (!firebaseAuthInstance) {
      setIsLoadingAuth(false);
      return;
    }
    const unsubscribe = onAuthStateChanged(firebaseAuthInstance, (user) => {
      setFirebaseUser(user);
      fetchOrRefreshCustomProfile(user);
    });
    return () => unsubscribe();
  }, []);

  const recordSuccessfulRequest = async () => {
    if (!firebaseUser || !customUserProfile || customUserProfile.isPremiumMember) {
      return;
    }
    const next = {
      requestsMadeToday: (customUserProfile.requestsMadeToday || 0) + 1,
      nextQuotaResetAt: customUserProfile.nextQuotaResetAt,
    };
    writeLocalCounter(firebaseUser.uid, next);
    setCustomUserProfile({ ...customUserProfile, ...next });
  };

  // Derived states
  const isPremium = customUserProfile?.isPremiumMember || false;
  const dailyLimit = customUserProfile?.quotas.daily_compare_limit ?? 0;
  const requestsMadeToday = customUserProfile?.requestsMadeToday ?? 0;

  let canMakeRequestCalculated = false;
  let requestsLeftTodayCalculated = 0;
  let nextQuotaResetTimeDisplayString: string | null = null;

  if (firebaseUser && customUserProfile) {
    if (isPremium || dailyLimit === -1) {
      canMakeRequestCalculated = true;
      requestsLeftTodayCalculated = Number.POSITIVE_INFINITY;
    } else {
      requestsLeftTodayCalculated = dailyLimit - requestsMadeToday;
      canMakeRequestCalculated = requestsLeftTodayCalculated > 0;
    }

    const resetTimestamp = customUserProfile.nextQuotaResetAt;
    if (resetTimestamp) {
      const diffMs = resetTimestamp - Date.now();
      if (diffMs <= 0) {
        nextQuotaResetTimeDisplayString = 'soon (refresh may be needed)';
      } else {
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
        if (diffHours > 0) {
          nextQuotaResetTimeDisplayString = `in approx. ${diffHours} hour${diffHours > 1 ? 's' : ''} and ${diffMinutes} minute${diffMinutes > 1 ? 's' : ''}`;
        } else if (diffMinutes > 0) {
          nextQuotaResetTimeDisplayString = `in approx. ${diffMinutes} minute${diffMinutes > 1 ? 's' : ''}`;
        } else {
          nextQuotaResetTimeDisplayString = 'in less than a minute';
        }
      }
    }
  } else if (firebaseUser && !customUserProfile && !isLoadingAuth) {
    canMakeRequestCalculated = false;
    requestsLeftTodayCalculated = 0;
    nextQuotaResetTimeDisplayString = 'Profile data unavailable';
  }

  return (
    <AuthContext.Provider value={{
      firebaseUser,
      customUserProfile,
      isLoadingAuth,
      canMakeRequest: canMakeRequestCalculated,
      requestsLeftToday: requestsLeftTodayCalculated,
      nextQuotaResetTimeDisplay: nextQuotaResetTimeDisplayString,
      recordSuccessfulRequest,
      refreshUserProfile: () => fetchOrRefreshCustomProfile(firebaseUser),
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider.');
  }
  return context;
};
