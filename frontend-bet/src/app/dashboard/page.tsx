// src/app/dashboard/page.tsx
"use client";

import React, { useState, useEffect } from 'react'; // Removed useCallback as local handleLogout is removed
import { useRouter } from 'next/navigation';
import {
  Sun,
  Moon,
  // LogOut, // LogoutButton imports its own icon
  UserCircle,
  Zap,
  AlertTriangle,
  BarChart3,
  ShieldCheck,
  TrendingUp,
  // Settings, // You can add a settings card if needed
  Bell, Search,
} from 'lucide-react';
import LogoutButton from "@/components/ui/LogoutButton"; // Assuming this is your reusable logout button
import { useAuth } from '@/contexts/AuthContext'; // Import your AuthContext hook

// Fallback only — real limit comes from `quotas.daily_compare_limit` returned by /api/users/me.
const FALLBACK_NORMAL_LIMIT = 5;

export default function DashboardPage() {
  const router = useRouter();
  // Get user data and auth state from AuthContext
  const {
    firebaseUser,
    customUserProfile,
    isLoadingAuth,
    requestsLeftToday, // Renamed from 'requestsLeft' for clarity
    nextQuotaResetTimeDisplay,
    refreshUserProfile // Optional: if you want a manual refresh button
  } = useAuth();

  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  // isLoading state from context (isLoadingAuth) will handle initial page load.
  // Local isLoading can be used for other specific actions if needed.

  // Effect for initial auth check and redirection if not logged in
  useEffect(() => {
    if (!isLoadingAuth && !firebaseUser) {
      console.log("Dashboard: User not authenticated, redirecting to login.");
      router.push('/auth/login');
    }
  }, [isLoadingAuth, firebaseUser, router]);

  // Theme management effects (can remain as they are)
  useEffect(() => {
    const storedTheme = localStorage.getItem('theme') as 'light' | 'dark' | null;
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (storedTheme) {
      setTheme(storedTheme);
    } else {
      setTheme(systemPrefersDark ? 'dark' : 'light');
    }
  }, []); // Runs once on mount to load theme preference

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]); // Runs when theme state changes

  const toggleTheme = () => {
    setTheme((prevTheme) => (prevTheme === 'light' ? 'dark' : 'light'));
  };

  // The LogoutButton component now handles its own logout logic.
  // The local handleLogout function is no longer needed if the top header is removed
  // and replaced by the LogoutButton component.

  // Show loading state while AuthContext is verifying authentication
  if (isLoadingAuth || (firebaseUser && !customUserProfile && !isLoadingAuth)) {
    // Also show loading if firebaseUser is present but customUserProfile hasn't loaded yet
    // (and initial auth check is done)
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-100 dark:bg-gray-900">
        <div className="flex flex-col items-center">
          <BarChart3 className="h-12 w-12 text-blue-600 dark:text-blue-400 animate-pulse mb-4" />
          <div className="text-xl font-semibold text-gray-700 dark:text-gray-300">
            {isLoadingAuth ? "Authenticating..." : "Loading User Profile..."}
          </div>
        </div>
      </div>
    );
  }

  // If after loading, there's no Firebase user, it means redirection should occur or user is not logged in.
  // The useEffect above handles redirection. This is a fallback or for brief moments before redirect.
  if (!firebaseUser) {
    return (
        <div className="flex items-center justify-center min-h-screen bg-gray-100 dark:bg-gray-900">
            <div className="text-xl font-semibold text-gray-700 dark:text-gray-300">
                Redirecting to login...
            </div>
        </div>
    );
  }

  // At this point, firebaseUser exists. We can use customUserProfile if available, or fallback to firebaseUser info.
  const userRole = customUserProfile?.role ?? 'normal';
  const isUserPremium = customUserProfile?.isPremiumMember || false;
  const isUserAdmin = userRole === 'admin';
  const dailyLimit = customUserProfile?.quotas.daily_compare_limit ?? FALLBACK_NORMAL_LIMIT;
  const currentRequestsLeft = customUserProfile ? requestsLeftToday : 0; // Use requestsLeftToday from context
  const userDisplayName = customUserProfile?.displayName || firebaseUser.displayName || "User";
  // const userEmail = customUserProfile?.email || firebaseUser.email;
  // const avatarUrl = customUserProfile?.avatarUrl || firebaseUser.photoURL;

  return (
    <div className="flex flex-col min-h-screen bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-gray-100 transition-colors duration-300">
      {/* If you have a global Navbar component, it would go here.
          It could also use useAuth() to display user info, theme toggle, and logout.
          For now, this page is standalone post-login.
      */}
      <main className="flex-grow container mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Card 1: Welcome/Stats */}
            <div
                className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out">
              <div className="flex items-center space-x-4 mb-4">
                <Zap className="h-10 w-10 text-purple-500 dark:text-purple-400"/> {/* Using Zap icon */}
                <div>
                  <h2 className="text-xl font-semibold text-gray-800 dark:text-white">Arbitrage Scanner</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400">Find market arbitrage opportunities.</p>
                </div>
              </div>
              <div className="mt-6"> {/* Added margin top for spacing */}
                <button
                    onClick={() => router.push('/arbitrage-scanner')} // Make sure '/arbitrage-scanner' is your target route
                    className="w-full bg-purple-600 hover:bg-purple-700 dark:bg-purple-700 dark:hover:bg-purple-800 text-white font-semibold py-3 px-4 rounded-lg shadow-md hover:shadow-lg transition-all duration-300 ease-in-out transform hover:scale-105 flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
                >
                  <Search className="h-5 w-5 mr-2"/> {/* Search icon on the button */}
                  Scan for Opportunities
                </button>
              </div>
            </div>

          {/* Card 2: User Status / Requests Left */}
          <div
              className={`p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out ${isUserPremium ? 'bg-gradient-to-br from-green-50 to-emerald-100 dark:from-green-800/30 dark:to-emerald-900/40' : 'bg-gradient-to-br from-yellow-50 to-amber-100 dark:from-yellow-800/30 dark:to-amber-900/40'}`}>
            <div className="flex items-center space-x-4 mb-4">
              {isUserPremium ? (
                  <ShieldCheck className="h-10 w-10 text-green-600 dark:text-green-400"/>
              ) : (
                  <AlertTriangle className="h-10 w-10 text-yellow-600 dark:text-yellow-400"/>
              )}
              <div>
                <h2 className="text-xl font-semibold text-gray-800 dark:text-white">
                  {isUserAdmin ? 'Admin Account' : isUserPremium ? 'Premium Account' : 'Standard Account'}
                </h2>
                {isUserPremium ? (
                  <p className="text-sm text-green-700 dark:text-green-300">
                    {isUserAdmin ? 'Full admin access — all features unlocked.' : 'Enjoy expanded analysis requests and tracking.'}
                  </p>
                ) : (
                  customUserProfile && ( // Ensure profile is loaded before displaying request info
                    <>
                      <p className="text-sm text-yellow-700 dark:text-yellow-300">
                        Daily Analysis Requests: <span className="font-bold">{currentRequestsLeft < 0 ? 0 : currentRequestsLeft} / {dailyLimit}</span> left.
                      </p>
                      {nextQuotaResetTimeDisplay && (
                        <p className="text-xs text-yellow-600 dark:text-yellow-200 mt-1">
                          Resets {nextQuotaResetTimeDisplay}.
                        </p>
                      )}
                    </>
                  )
                )}
              </div>
            </div>
            {!isUserPremium && (
              <button
                onClick={() => router.push('/pricing')} // Link to your pricing/upgrade page
                className="mt-4 w-full bg-gradient-to-r from-purple-500 via-pink-500 to-red-500 hover:from-purple-600 hover:via-pink-600 hover:to-red-600 text-white font-semibold py-3 px-4 rounded-lg shadow-md hover:shadow-lg transition-all duration-300 ease-in-out transform hover:scale-105 flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
              >
                <Zap className="h-5 w-5 mr-2" /> Upgrade to Pro (Future)
              </button>
            )}
            {customUserProfile && !isUserPremium && refreshUserProfile && (
                 <button
                    onClick={async () => { await refreshUserProfile(); }}
                    className="mt-2 w-full text-xs text-blue-600 dark:text-sky-400 hover:underline"
                >
                    Refresh Quota Status
                </button>
            )}
          </div>

          {/* Card 3: Notifications */}
          <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out">
            <div className="flex items-center space-x-4 mb-4">
              <Bell className="h-10 w-10 text-blue-500 dark:text-blue-400" />
              <div>
                <h2 className="text-xl font-semibold text-gray-800 dark:text-white">Notifications</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Recent alerts and updates.</p>
              </div>
            </div>
            <div className="space-y-3">
                <p className="text-sm text-gray-700 dark:text-gray-300">📢 Welcome to your dashboard!</p>
                {/* Add more notifications here */}
            </div>
          </div>

          {/* Card 4: Pro Analysis Link (Conditional or always show) */}
          {/* You might always show this and let the ProAnalysisPage handle its own guarding */}
          <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out md:col-span-1 lg:col-span-1">
            <div className="flex items-center space-x-4 mb-4">
              <Zap className="h-10 w-10 text-purple-500 dark:text-purple-400" />
              <div>
                <h2 className="text-xl font-semibold text-gray-800 dark:text-white">Team Analysis</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Compare professional teams.</p>
              </div>
            </div>
            <button
              onClick={() => router.push('/pro-analysis')}
              className="mt-4 w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-4 rounded-lg transition-colors duration-300 ease-in-out shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
            >
              Go to Analysis
            </button>
          </div>

          {/* Logout Button Card/Item - using the classes you provided for it */}
          <div className="bg-white dark:bg-gray-800 p-3 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out flex items-center justify-center">
            <LogoutButton
              showText={true}
              text="Sign Out"
              className="flex items-center w-auto p-2 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-700/50 rounded-md !ring-0 !focus:ring-0" // Adjusted classes
              iconClassName="h-5 w-5 mr-2"
            />
          </div>

           {/* Card 6: Quick Actions (Example for more content) */}
           <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 ease-in-out md:col-span-2 lg:col-span-1">
            <div className="flex items-center space-x-4 mb-4">
              <BarChart3 className="h-10 w-10 text-indigo-500 dark:text-indigo-400" />
              <div>
                <h2 className="text-xl font-semibold text-gray-800 dark:text-white">Quick Actions</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Start a new analysis or report.</p>
              </div>
            </div>
            <div className="space-y-3">
              <button
                onClick={() => router.push('/pro-analysis')}
                className="w-full bg-indigo-500 hover:bg-indigo-600 text-white font-medium py-2.5 px-4 rounded-lg transition-colors duration-300 ease-in-out"
              >
                New Team Analysis
              </button>
              {/* <button className="w-full bg-sky-500 hover:bg-sky-600 text-white font-medium py-2.5 px-4 rounded-lg transition-colors duration-300 ease-in-out">Generate Monthly Report</button> */}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}