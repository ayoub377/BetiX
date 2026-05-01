// src/app/pro-analysis/page.tsx
"use client";

import React, { useEffect, useState } from 'react';
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext"; // Ensure this path is correct
import { apiClient, isApiError } from '@/lib/apiClient';
import Button from "@/components/ui/Button"; // Assuming you have this custom Button

// Interfaces (PlayerDetail, PositionComparison, ApiFullResponse)
interface PlayerDetail {
  name: string;
  jersey_number: number | string;
  market_value: number | string;
}

interface PositionComparison {
  position: string;
  home_player: PlayerDetail | null;
  away_player: PlayerDetail | null;
  result: 'home_higher' | 'away_higher' | 'equal' | 'home_only' | 'away_only' | 'no_players';
}

type ComparisonItemsArray = PositionComparison[];

interface ApiFullResponse {
  home_team: string;
  away_team: string;
  comparison: ComparisonItemsArray;
}

// Fallback only — the real limit comes from `quotas.daily_compare_limit` returned by /api/users/me.
const FALLBACK_NORMAL_LIMIT = 5;

export default function ProAnalysisPage() {
  const {
    firebaseUser,
    isLoadingAuth,
    customUserProfile, // Contains isPremiumMember and requestsMadeToday
    canMakeRequest,    // Derived in AuthContext: true if user can make an analysis request
    requestsLeftToday, // Derived in AuthContext: How many requests are left for non-premium today
    nextQuotaResetTimeDisplay, // Derived in AuthContext: User-friendly string for when quota resets
    recordSuccessfulRequest, // Function from AuthContext to call after a successful analysis
    refreshUserProfile // Function from AuthContext to manually trigger a profile refresh
  } = useAuth();

  const router = useRouter();

  const [team1Input, setTeam1Input] = useState('');
  const [team2Input, setTeam2Input] = useState('');
  const [analysisResult, setAnalysisResult] = useState<ComparisonItemsArray | null>(null);
  const [isLoadingApi, setIsLoadingApi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiHomeTeamName, setApiHomeTeamName] = useState<string>('');
  const [apiAwayTeamName, setApiAwayTeamName] = useState<string>('');

  useEffect(() => {
    if (!isLoadingAuth) { // Wait for auth check to complete
      if (!firebaseUser) {
        console.log("ProAnalysis: User not authenticated, redirecting to login.");
        router.push('/auth/login'); // Your login page route
      }
      // If user is authenticated, the rendering logic below will handle
      // "limit reached" messages or allow access based on `canMakeRequest`.
    }
  }, [isLoadingAuth, firebaseUser, router]);

  // Clear error messages if the user's ability to make requests changes (e.g., quota reset)
  useEffect(() => {
    if (canMakeRequest && error && (error.includes("limit") || error.includes("requests") || error.includes("Access denied"))) {
        setError(null);
    }
  }, [canMakeRequest, error]);

  const handleCompareTeams = async () => {
    if (!firebaseUser) {
        setError("You must be logged in to perform analysis.");
        return;
    }
    // Also check if customUserProfile is loaded before relying on canMakeRequest,
    // though canMakeRequest itself considers this.
    if (!customUserProfile && !isLoadingAuth) {
        setError("User profile is still loading or not available. Please try again shortly.");
        // Optionally trigger a profile refresh if it seems stuck
        // await refreshUserProfile();
        return;
    }
    if (!canMakeRequest) {
      const limitMessage = customUserProfile?.isPremiumMember
        ? "An issue occurred with your account status. Please contact support."
        : `You have used all your daily requests. Your quota will reset ${nextQuotaResetTimeDisplay || 'soon'}.`;
      setError(limitMessage);
      return;
    }

    const homeTeamName = team1Input.trim();
    const awayTeamName = team2Input.trim();

    if (!homeTeamName || !awayTeamName) {
      setError("Please enter names for both teams.");
      return;
    }
    if (homeTeamName.toLowerCase() === awayTeamName.toLowerCase()) {
      setError("Please enter two different team names.");
      return;
    }

    setIsLoadingApi(true);
    setError(null);
    setAnalysisResult(null);
    setApiHomeTeamName('');
    setApiAwayTeamName('');

    try {
      const response = await apiClient.get<ApiFullResponse>(
        `/clubs/compare/${encodeURIComponent(homeTeamName)}/${encodeURIComponent(awayTeamName)}`
      );

      if (response.data && response.data.comparison && response.data.comparison.length > 0) {
        setAnalysisResult(response.data.comparison);
        setApiHomeTeamName(response.data.home_team);
        setApiAwayTeamName(response.data.away_team);
        // Record successful request (AuthContext handles premium check internally)
        await recordSuccessfulRequest();
      } else {
        console.error("API response is missing data or comparison array is empty:", response.data);
        setAnalysisResult([]); // Still set to empty array to clear previous results table
        setError(response.data?.comparison?.length === 0 ? "Analysis complete, but no direct player matchups were found for these teams." : "Received incomplete or empty comparison data from the server.");
      }
    } catch (err) {
      console.error("--- Full Axios Error Object Below ---");
      console.error(err);

      if (isApiError(err)) {
        console.log("--- Axios Error Detected ---");
        if (err.response) {
          console.error("Axios Error Response Data:", err.response.data);
          console.error("Axios Error Response Status:", err.response.status);
          if (err.response.status === 401 || err.response.status === 403) {
             setError("Authentication error or insufficient permissions. Please log in again or check your account status.");
          } else if (err.response.status === 429) { // Example: Backend indicates rate limit explicitly
             setError(`Daily request limit reached. Your quota will reset ${nextQuotaResetTimeDisplay || 'soon'}.`);
             // Force a refresh of profile to get latest quota from backend
             if (refreshUserProfile) await refreshUserProfile();
          } else {
            let uiMessage = "Failed to fetch analysis. Please check team names or try again.";
            const data = err.response.data;
            if (data) {
              if (typeof data.detail === 'string') uiMessage = data.detail;
              else if (typeof data.message === 'string') uiMessage = data.message;
              else if (typeof data === 'string') uiMessage = data;
              else { try { uiMessage = JSON.stringify(data); } catch (e) { /* ignore stringify error */ } }
            }
            setError(uiMessage);
          }
        } else if (err.request) {
          console.error("Axios Error Request Data:", err.request);
          setError("No response received from the server. Check network and backend status.");
        } else {
          console.error('Axios Error Message:', err.message);
          setError("An error occurred while setting up the request: " + err.message);
        }
      } else {
        console.error("--- Non-Axios Error Detected ---");
        setError("An unexpected non-Axios error occurred.");
      }
    } finally {
      setIsLoadingApi(false);
    }
  };

  const formatMarketValue = (value: number | string | undefined): string => {
    if (value === undefined || value === null) return 'N/A';
    if (typeof value === 'string') {
      const num = parseFloat(value.replace(/[^0-9.-]+/g,""));
      if (!isNaN(num)) return `€${(num / 1000000).toFixed(1)}M`;
      return value;
    }
    if (typeof value === 'number') {
      return `€${(value / 1000000).toFixed(1)}M`;
    }
    return 'N/A';
  };

  const displayHomeTeamName = apiHomeTeamName || team1Input.trim();
  const displayAwayTeamName = apiAwayTeamName || team2Input.trim();

  // 1. Handle Authentication or Custom Profile Loading State
  if (isLoadingAuth || (firebaseUser && !customUserProfile && !isLoadingAuth)) {
    // Show loading if initial auth check is happening OR
    // if firebaseUser exists but customUserProfile hasn't loaded yet (and auth loading is finished)
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-100 dark:bg-slate-900">
        <div className="text-xl font-semibold text-gray-700 dark:text-gray-300">
          {isLoadingAuth ? "Authenticating..." : "Loading user profile..."}
        </div>
      </div>
    );
  }

  // 2. Handle Not Logged In (useEffect also attempts to redirect)
  if (!firebaseUser) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 dark:bg-slate-900 p-6 text-center">
        <h2 className="text-2xl font-bold text-red-500 dark:text-red-400 mb-4">Access Denied</h2>
        <p className="text-gray-700 dark:text-gray-300 mb-6">
          You need to be logged in to access this page.
        </p>
        <Button
          onClick={() => router.push('/auth/login')}
          className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow-md transition"
        >
          Go to Login
        </Button>
      </div>
    );
  }

  // 3. Handle Authenticated User who has run out of daily requests (and is not premium)
  // This relies on customUserProfile being loaded.
  if (customUserProfile && !customUserProfile.isPremiumMember && !canMakeRequest) {
     return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 dark:bg-slate-900 p-6 text-center">
        <h2 className="text-2xl font-bold text-red-500 dark:text-red-400 mb-4">Daily Limit Reached</h2>
        <p className="text-gray-700 dark:text-gray-300 mb-2">
          You have used your {(customUserProfile?.quotas.daily_compare_limit ?? FALLBACK_NORMAL_LIMIT)} free analysis requests for today.
        </p>
        {nextQuotaResetTimeDisplay && (
            <p className="text-gray-600 dark:text-gray-400 mb-1">Your requests will reset {nextQuotaResetTimeDisplay}.</p>
        )}
        <p className="text-gray-600 dark:text-gray-400 mb-6">
          Please try again later or consider upgrading for unlimited requests (feature coming soon!).
        </p>
        <Button
            variant="link"
            onClick={() => router.push('/dashboard')}
            className="mt-4 text-blue-600 dark:text-sky-400"
        >
            Back to Dashboard
        </Button>
        {refreshUserProfile && ( // Show refresh button if function is available
            <Button
                variant="outline"
                onClick={async () => {
                    await refreshUserProfile();
                    // isLoadingAuth will be set to false by AuthContext after refresh
                }}
                className="mt-2 text-sm"
            >
                Refresh Quota Status
            </Button>
        )}
      </div>
    );
  }

  // 4. Render Page Content if authorized and has requests left (or is premium)
  return (
    <div className="flex flex-col min-h-screen bg-gray-50 dark:bg-slate-900 font-sans">
      <main className="flex-grow container mx-auto px-4 py-8 md:py-12">
        <div className="text-center mb-10 md:mb-12">
          <h1 className=" cursor-pointer text-3xl sm:text-4xl md:text-5xl font-bold text-gray-800 dark:text-gray-100">
            Team Analysis
          </h1>
          <p className="text-md sm:text-lg text-gray-600 dark:text-gray-300 mt-2">
            Welcome, {customUserProfile?.displayName || firebaseUser.displayName || firebaseUser.email}!
          </p>
          {/* Display request count information */}
          {customUserProfile && (
            <div className="mt-2 text-sm">
              {customUserProfile.isPremiumMember ? (
                <p className="font-medium text-green-600 dark:text-emerald-400">Pro Account: Unlimited Requests</p>
              ) : (
                <>
                  <p className="font-medium text-blue-600 dark:text-sky-400">
                    Daily requests remaining: <span className="font-bold">{requestsLeftToday < 0 ? 0 : requestsLeftToday}</span> / {(customUserProfile?.quotas.daily_compare_limit ?? FALLBACK_NORMAL_LIMIT)}
                  </p>
                  {requestsLeftToday <= 0 && nextQuotaResetTimeDisplay && (
                     <p className="text-xs text-gray-500 dark:text-gray-400">Next reset: {nextQuotaResetTimeDisplay}</p>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        <div className="max-w-3xl mx-auto bg-white dark:bg-slate-800 p-6 sm:p-8 rounded-xl shadow-2xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
              <label htmlFor="team1" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Team 1</label>
              <input
                type="text" id="team1" value={team1Input} onChange={(e) => setTeam1Input(e.target.value)}
                placeholder="Enter first team name"
                className="w-full p-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 dark:bg-slate-700 dark:text-gray-100"
              />
            </div>
            <div>
              <label htmlFor="team2" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Team 2</label>
              <input
                type="text" id="team2" value={team2Input} onChange={(e) => setTeam2Input(e.target.value)}
                placeholder="Enter second team name"
                className="w-full p-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 dark:bg-slate-700 dark:text-gray-100"
              />
            </div>
          </div>
          <button
            onClick={handleCompareTeams}
            disabled={isLoadingApi || !team1Input.trim() || !team2Input.trim() || !canMakeRequest} // Disable if cannot make request
            className="w-full bg-blue-600 hover:bg-blue-700 dark:bg-sky-600 dark:hover:bg-sky-700 text-white font-semibold py-3 px-4 rounded-lg shadow-md transition duration-150 ease-in-out disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
          >
            {isLoadingApi ? (
              <><svg className="cursor-pointer animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Analyzing...</>
            ) : (
              'Compare Teams'
            )}
          </button>
          {error && (
            <p className="mt-4 text-center text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 p-3 rounded-md">
              {error}
            </p>
          )}
        </div>

        {analysisResult && !isLoadingApi && (
          <div className="mt-10 md:mt-12 max-w-5xl mx-auto bg-white dark:bg-slate-800 p-6 sm:p-8 rounded-xl shadow-xl">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-800 dark:text-gray-100 mb-6 text-center">
              Analysis: {displayHomeTeamName} vs {displayAwayTeamName}
            </h2>
            {analysisResult.length > 0 ? (
              <div>
                <h3 className="text-xl font-semibold text-gray-700 dark:text-gray-200 mb-4">Position-by-Position Comparison</h3>
                <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-slate-700">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-slate-700">
                    <thead className="bg-gray-100 dark:bg-slate-700">
                      <tr>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Position</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{displayHomeTeamName}</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Value</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">{displayAwayTeamName}</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Value</th>
                        <th scope="col" className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Comparison</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-slate-700">
                      {analysisResult.map((item, index) => (
                        <tr key={index} className={index % 2 === 0 ? 'bg-white dark:bg-slate-800' : 'bg-gray-50 dark:bg-slate-700/50'}>
                          <td className="px-3 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100">{item.position}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{item.home_player ? `${item.home_player.name} (#${item.home_player.jersey_number})` : 'N/A'}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{item.home_player ? formatMarketValue(item.home_player.market_value) : 'N/A'}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{item.away_player ? `${item.away_player.name} (#${item.away_player.jersey_number})` : 'N/A'}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{item.away_player ? formatMarketValue(item.away_player.market_value) : 'N/A'}</td>
                          <td className="px-3 py-3 whitespace-nowrap text-sm">
                            {item.result === 'home_higher' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-700 dark:text-green-100">Home Higher</span>}
                            {item.result === 'away_higher' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-700 dark:text-red-100">Away Higher</span>}
                            {item.result === 'equal' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-600 dark:text-yellow-100">Equal Value</span>}
                            {item.result === 'home_only' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800 dark:bg-blue-700 dark:text-blue-100">Home Only</span>}
                            {item.result === 'away_only' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-purple-100 text-purple-800 dark:bg-purple-700 dark:text-purple-100">Away Only</span>}
                            {item.result === 'no_players' && <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-100 text-gray-800 dark:bg-gray-600 dark:text-gray-100">N/A</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
                 <p className="text-center text-gray-600 dark:text-gray-300 mt-4">
                   Analysis complete, but no direct player matchups found or data was empty.
                 </p>
            )}
          </div>
        )}
      </main>
      {/* Consider adding a <Footer /> component here */}
    </div>
  );
}