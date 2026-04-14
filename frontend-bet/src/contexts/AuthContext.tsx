// src/contexts/AuthContext.tsx
"use client";

import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { onAuthStateChanged, User as FirebaseUser } from 'firebase/auth';
import { auth as firebaseAuthInstance } from '@/lib/firebaseConfig';

const DAILY_NORMAL_USER_MAX_REQUESTS = 5;

export interface CustomUserProfile {
  uid: string;
  email: string | null;
  displayName: string | null;
  isPremiumMember: boolean;
  requestsMadeToday: number;    // Requests made in the current 24h window
  nextQuotaResetAt: number;     // Timestamp (milliseconds) when quota resets
}

export interface AuthContextType {
  firebaseUser: FirebaseUser | null;
  customUserProfile: CustomUserProfile | null;
  isLoadingAuth: boolean;
  canMakeRequest: boolean;          // True if user can make an analysis request
  requestsLeftToday: number;        // How many requests are left for non-premium today
  nextQuotaResetTimeDisplay: string | null; // User-friendly string for when quota resets
  recordSuccessfulRequest: () => Promise<void>; // Call after a successful analysis
  refreshUserProfile: () => Promise<void>;    // Manually trigger a profile refresh
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

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
    // Start loading custom profile data
    // setIsLoadingAuth(true); // This can cause a flicker if called frequently. Manage carefully.

    try {
      // =======================================================================
      // ** START: REAL IMPLEMENTATION (Replace MOCK below with this) **
      // =======================================================================
      // const token = await user.getIdToken();
      // const response = await fetch(`/api/your-backend/user-profile`, { // Your API endpoint
      //   headers: { 'Authorization': `Bearer ${token}` }
      // });
      // if (!response.ok) {
      //   // Handle case where profile might not exist yet for a new Firebase user
      //   if (response.status === 404) {
      //     console.log("AuthContext: No custom profile found for user, creating/using defaults.");
      //     // You might have a separate endpoint to create a default profile
      //     // For now, we can set a default local one, but backend should ideally create it
      //     const defaultProfile: CustomUserProfile = {
      //       uid: user.uid, email: user.email, displayName: user.displayName,
      //       isPremiumMember: false, requestsMadeToday: 0,
      //       nextQuotaResetAt: Date.now() + 24 * 60 * 60 * 1000, // Default reset in 24h
      //     };
      //     setCustomUserProfile(defaultProfile);
      //     // Optionally, trigger a backend call here to persist this default profile
      //   } else {
      //     throw new Error(`Failed to fetch profile: ${response.statusText}`);
      //   }
      // } else {
      //    const profileData: CustomUserProfile = await response.json();
      //    setCustomUserProfile(profileData); // Backend provides daily reset logic
      // }
      // =======================================================================
      // ** END: REAL IMPLEMENTATION **
      // =======================================================================


      // =======================================================================
      // ** START: MOCK IMPLEMENTATION (for client-side demo) **
      // ** WARNING: THIS IS NOT SECURE AND FOR DEMO ONLY. BACKEND MUST HANDLE THIS. **
      // =======================================================================
      console.log("AuthContext: Mocking fetch/refresh for custom profile for", user.uid);
      const isMockPremium = user.email === 'pro@example.com'; // Example of a premium user

      const storageKey = `dailyUsage_${user.uid}`;
      let storedDataString = localStorage.getItem(storageKey);
      let currentProfileData: CustomUserProfile;

      if (storedDataString) {
        let storedProfile = JSON.parse(storedDataString) as Partial<CustomUserProfile> & { lastKnownReset?: number };
        // Check if 24 hours have passed since the last known reset or initial setup
        if (storedProfile.nextQuotaResetAt && Date.now() > storedProfile.nextQuotaResetAt) {
          console.log("AuthContext (Mock): Daily quota reset for user", user.uid);
          currentProfileData = {
            uid: user.uid, email: user.email, displayName: user.displayName,
            isPremiumMember: isMockPremium, // Re-evaluate premium status if needed
            requestsMadeToday: 0,
            nextQuotaResetAt: Date.now() + 24 * 60 * 60 * 1000,
          };
        } else {
          currentProfileData = {
            uid: user.uid, email: user.email, displayName: user.displayName,
            isPremiumMember: isMockPremium,
            requestsMadeToday: storedProfile.requestsMadeToday || 0,
            nextQuotaResetAt: storedProfile.nextQuotaResetAt || (Date.now() + 24 * 60 * 60 * 1000),
          };
        }
      } else {
        // First time seeing this user in this session/storage
        currentProfileData = {
          uid: user.uid, email: user.email, displayName: user.displayName,
          isPremiumMember: isMockPremium, requestsMadeToday: 0,
          nextQuotaResetAt: Date.now() + 24 * 60 * 60 * 1000,
        };
      }
      localStorage.setItem(storageKey, JSON.stringify(currentProfileData));
      setCustomUserProfile(currentProfileData);
      // =======================================================================
      // ** END: MOCK IMPLEMENTATION **
      // =======================================================================

    } catch (error) {
      console.error("Error fetching/refreshing custom user profile:", error);
      setCustomUserProfile(null); // Fallback if profile fetch fails
    } finally {
      setIsLoadingAuth(false);
    }
  };

  useEffect(() => {
    // Guard: firebaseAuthInstance is undefined during SSR / static prerender
    if (!firebaseAuthInstance) {
      setIsLoadingAuth(false);
      return;
    }
    const unsubscribe = onAuthStateChanged(firebaseAuthInstance, (user) => {
      setFirebaseUser(user); // Set Firebase user immediately
      fetchOrRefreshCustomProfile(user); // Then fetch/refresh custom profile which sets isLoadingAuth
    });
    return () => unsubscribe();
  }, []);

  const recordSuccessfulRequest = async () => {
    if (!firebaseUser || !customUserProfile || customUserProfile.isPremiumMember) {
      // No need to record for guests or if user is premium (they have unlimited)
      return;
    }

    try {
      // =======================================================================
      // ** START: REAL IMPLEMENTATION (Replace MOCK below with this) **
      // =======================================================================
      // const token = await firebaseUser.getIdToken();
      // const response = await fetch(`/api/your-backend/user/record-request`, { // Your API endpoint
      //   method: 'POST',
      //   headers: { 'Authorization': `Bearer ${token}` }
      // });
      // if (!response.ok) {
      //   throw new Error(`Failed to record request: ${response.statusText}`);
      // }
      // const updatedProfile: CustomUserProfile = await response.json(); // Backend returns updated profile
      // setCustomUserProfile(updatedProfile);
      // =======================================================================
      // ** END: REAL IMPLEMENTATION **
      // =======================================================================

      // =======================================================================
      // ** START: MOCK IMPLEMENTATION **
      // ** WARNING: THIS IS NOT SECURE. BACKEND MUST HANDLE THIS. **
      // =======================================================================
      console.log("AuthContext (Mock): Recording successful request for", firebaseUser.uid);
      const newRequestsMade = (customUserProfile.requestsMadeToday || 0) + 1;
      // Ensure nextQuotaResetAt is preserved or re-evaluated if necessary by backend logic
      const updatedProfile = { ...customUserProfile, requestsMadeToday: newRequestsMade };
      localStorage.setItem(`dailyUsage_${firebaseUser.uid}`, JSON.stringify(updatedProfile));
      setCustomUserProfile(updatedProfile);
      // =======================================================================
      // ** END: MOCK IMPLEMENTATION **
      // =======================================================================

    } catch (error) {
      console.error("Failed to record successful request:", error);
      // You might want to notify the user or handle this error,
      // e.g., by not decrementing the local count if the backend call failed.
    }
  };

  // Derived states
  const isActuallyPremium = customUserProfile?.isPremiumMember || false;
  const currentRequestsMadeToday = customUserProfile?.requestsMadeToday || 0;

  let canMakeRequestCalculated = false;
  let requestsLeftTodayCalculated = 0;
  let nextQuotaResetTimeDisplayString: string | null = null;

  if (firebaseUser && customUserProfile) { // User logged in and their custom profile is loaded
    if (isActuallyPremium) {
      canMakeRequestCalculated = true;
      requestsLeftTodayCalculated = Infinity; // Or a very large number / "Unlimited"
    } else {
      requestsLeftTodayCalculated = DAILY_NORMAL_USER_MAX_REQUESTS - currentRequestsMadeToday;
      canMakeRequestCalculated = requestsLeftTodayCalculated > 0;
    }

    if (customUserProfile.nextQuotaResetAt) {
      const resetTimestamp = customUserProfile.nextQuotaResetAt;
      const now = Date.now();
      const diffMs = resetTimestamp - now;

      if (diffMs <= 0) { // Quota should have reset or will reset very imminently
        nextQuotaResetTimeDisplayString = "soon (refresh may be needed)";
        // Potentially, canMakeRequestCalculated could be true if requestsLeftTodayCalculated was based on stale data.
        // A robust backend would provide the already reset count.
        // For the mock, if reset time passed, we rely on next fetchOrRefresh to fix counts.
      } else {
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
        if (diffHours > 0) {
          nextQuotaResetTimeDisplayString = `in approx. ${diffHours} hour${diffHours > 1 ? 's' : ''} and ${diffMinutes} minute${diffMinutes > 1 ? 's' : ''}`;
        } else if (diffMinutes > 0) {
          nextQuotaResetTimeDisplayString = `in approx. ${diffMinutes} minute${diffMinutes > 1 ? 's' : ''}`;
        } else {
          nextQuotaResetTimeDisplayString = `in less than a minute`;
        }
      }
    }
  } else if (firebaseUser && !customUserProfile && !isLoadingAuth) {
    // User logged in, auth loading finished, but custom profile is null (e.g., fetch error)
    // Treat as unable to make requests for safety
    canMakeRequestCalculated = false;
    requestsLeftTodayCalculated = 0;
    nextQuotaResetTimeDisplayString = "Profile data unavailable";
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
      refreshUserProfile: () => fetchOrRefreshCustomProfile(firebaseUser) // Expose a way to manually refresh
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