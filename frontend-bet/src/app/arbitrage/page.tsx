// src/app/arbitrage/page.tsx (or your preferred path)
"use client";

import React, { useState, useEffect } from 'react';
import axios from 'axios';
// import Navbar from '@/components/layout/Navbar'; // Assuming you have a Navbar
// import Footer from '@/components/layout/Footer'; // Assuming you have a Footer

// Updated interface to match the backend response structure
interface ArbitrageOpportunity {
  match_id: string;
  match_name: string;
  match_start_time_unix: number;
  match_start_time_iso: string;
  hours_to_start: number;
  sport_key: string;
  sport_title: string;
  best_outcome_odds: {
    [outcomeName: string]: [bookmakerName: string, odds: number];
  };
  total_implied_odds: number;
  profit_margin_percentage: number;
}

// Corresponds to ArbitrageResponseModel from backend
interface ArbitrageResponse {
  message: string;
  opportunities_count: number;
  opportunities: ArbitrageOpportunity[];
}

// Add this new interface for calculated stakes
interface CalculatedStakeInfo {
  outcomeName: string;
  bookmakerName: string;
  odds: number;
  stake: number;
  potentialReturn: number;
}

// Helper to format time ago
const timeAgo = (dateString: string): string => {
  const date = new Date(dateString);
  const now = new Date();
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  const minutes = Math.round(seconds / 60);
  const hours = Math.round(minutes / 60);

  if (seconds < 60) return `${seconds} sec ago`;
  if (minutes < 60) return `${minutes} min ago`;
  if (hours < 24) return `${hours} hr ago`;
  return date.toLocaleDateString();
};

// Loading Skeleton component
const OpportunitySkeleton = () => (
  <div className="bg-white dark:bg-slate-800 p-6 rounded-lg shadow-lg animate-pulse">
    <div className="h-6 bg-gray-200 dark:bg-slate-700 rounded w-3/4 mb-3"></div>
    <div className="h-4 bg-gray-200 dark:bg-slate-700 rounded w-1/2 mb-4"></div>
    <div className="space-y-3">
      {[1, 2, 3].map(i => ( // Added a third item for better skeleton representation
        <div key={i} className="flex justify-between items-center p-3 bg-gray-50 dark:bg-slate-700/50 rounded-md">
          <div>
            <div className="h-4 bg-gray-300 dark:bg-slate-600 rounded w-24 mb-1"></div>
            <div className="h-3 bg-gray-300 dark:bg-slate-600 rounded w-20"></div>
          </div>
          <div className="h-6 bg-gray-300 dark:bg-slate-600 rounded w-12"></div>
        </div>
      ))}
    </div>
    <div className="mt-4 flex justify-between items-center">
      <div className="h-8 bg-green-200 dark:bg-green-700 rounded w-20"></div>
      <div className="h-3 bg-gray-200 dark:bg-slate-700 rounded w-24"></div>
    </div>
     <div className="mt-4 h-8 bg-sky-200 dark:bg-sky-700 rounded w-full"></div> {/* Placeholder for button */}
  </div>
);

const REGIONS = [
  { value: 'eu', label: 'Europe (EU)' },
  { value: 'us', label: 'United States (US)' },
  { value: 'uk', label: 'United Kingdom (UK)' },
  { value: 'au', label: 'Australia (AU)' },
];

// Arbitrage Calculator Modal Component
interface ArbitrageCalculatorModalProps {
  isOpen: boolean;
  onClose: () => void;
  opportunity: ArbitrageOpportunity | null;
  totalAmount: string;
  onTotalAmountChange: (value: string) => void;
  stakes: CalculatedStakeInfo[];
  // profitMarginPercentage will be derived from opportunity inside the modal
  // totalImpliedOdds will be derived from opportunity inside the modal
}

const ArbitrageCalculatorModal: React.FC<ArbitrageCalculatorModalProps> = ({
  isOpen,
  onClose,
  opportunity,
  totalAmount,
  onTotalAmountChange,
  stakes,
}) => {
  if (!isOpen || !opportunity) return null;

  const numericTotalAmount = parseFloat(totalAmount) || 0;
  const totalReturnValue = numericTotalAmount > 0 && opportunity.total_implied_odds > 0 && opportunity.total_implied_odds < 100
    ? (numericTotalAmount / opportunity.total_implied_odds)
    : 0;
  const totalProfit = totalReturnValue > 0 ? totalReturnValue - numericTotalAmount : 0;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 backdrop-blur-sm flex items-center justify-center z-50 p-4 transition-opacity duration-300 ease-in-out"
         style={{ opacity: isOpen ? 1 : 0 }} // Control opacity for smooth transition
    >
      <div className="bg-white dark:bg-slate-800 p-6 rounded-xl shadow-2xl w-full max-w-md sm:max-w-lg transform transition-all duration-300 ease-in-out scale-95 opacity-0 animate-modalShow"
           style={{ animationFillMode: 'forwards' }} // Keep final state of animation
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl sm:text-2xl font-semibold text-gray-800 dark:text-gray-100">
            Arbitrage Calculator
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 p-1 rounded-full transition-colors"
            aria-label="Close modal"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          </button>
        </div>

        <p className="text-sm text-gray-700 dark:text-gray-300 mb-1 truncate" title={opportunity.match_name}>
          Match: <span className="font-medium">{opportunity.match_name}</span>
        </p>
        <p className="text-sm text-red-500 dark:text-red-400 font-semibold mb-4">
          Guaranteed Profit Margin: {opportunity.profit_margin_percentage.toFixed(2)}%
        </p>

        <div className="mb-5">
          <label htmlFor="totalBet" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Total Bet Amount (€)
          </label>
          <input
            type="number"
            id="totalBet"
            value={totalAmount}
            onChange={(e) => onTotalAmountChange(e.target.value)}
            placeholder="e.g., 100"
            min="1" // Min bet usually 1
            step="any"
            className="w-full p-3 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 dark:bg-slate-700 dark:text-gray-100 text-lg"
          />
        </div>

        {stakes.length > 0 && numericTotalAmount > 0 && (
          <div className="space-y-3 mb-5">
            <h3 className="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Stakes per Outcome:</h3>
            {stakes.map((calc, index) => (
              <div key={index} className="p-3 bg-gray-100 dark:bg-slate-700 rounded-lg text-sm">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-medium text-gray-800 dark:text-gray-100">{calc.outcomeName}</span>
                  <span className="font-semibold text-gray-700 dark:text-gray-200">
                    Bet: <span className="text-blue-600 dark:text-sky-400">€{calc.stake.toFixed(2)}</span>
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs text-gray-500 dark:text-gray-400">
                   <span>@{calc.odds.toFixed(2)} on {calc.bookmakerName}</span>
                   <span>Returns: €{calc.potentialReturn.toFixed(2)}</span>
                </div>
              </div>
            ))}
            <div className="mt-5 pt-4 border-t border-gray-200 dark:border-slate-600">
              <div className="flex justify-between text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">
                <span>Total Stake:</span>
                <span>€{numericTotalAmount.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm font-semibold text-green-600 dark:text-green-400 mb-1">
                <span>Guaranteed Return (per outcome):</span>
                <span>€{totalReturnValue.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-md font-bold text-green-500 dark:text-green-400">
                <span>Guaranteed Profit:</span>
                <span>€{totalProfit.toFixed(2)}</span>
              </div>
            </div>
          </div>
        )}
        {numericTotalAmount > 0 && stakes.length === 0 && (
            <p className="text-sm text-center text-yellow-600 dark:text-yellow-400 py-4">Calculating stakes or issue with odds data...</p>
        )}
         {numericTotalAmount <= 0 && (
            <p className="text-sm text-center text-gray-500 dark:text-gray-400 py-4">Enter a total bet amount greater than 0.</p>
        )}


        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2.5 bg-gray-200 dark:bg-slate-600 text-gray-800 dark:text-gray-100 rounded-lg hover:bg-gray-300 dark:hover:bg-slate-500 transition text-sm font-medium"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};


export default function ArbitragePage() {
  const [opportunities, setOpportunities] = useState<ArbitrageOpportunity[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const [region, setRegion] = useState<string>('eu');
  const [cutoff, setCutoff] = useState<string>('0.01');
  const [sports, setSports] = useState<string>('');
  const [includeStartedMatches, setIncludeStartedMatches] = useState<boolean>(false);

  // State for the calculator modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedOpportunityForCalc, setSelectedOpportunityForCalc] = useState<ArbitrageOpportunity | null>(null);
  const [totalBetAmount, setTotalBetAmount] = useState<string>('100');
  const [calculatedStakes, setCalculatedStakes] = useState<CalculatedStakeInfo[]>([]);

  const fetchOpportunities = async () => {
    setIsLoading(true);
    setError(null);
    setHasSearched(true);
    try {
      const params: Record<string, any> = {
        region: region,
        cutoff: parseFloat(cutoff) || 0.0,
        include_started_matches: includeStartedMatches,
      };
      if (sports.trim() !== '') {
        params.sports = sports.trim();
      }

      const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000/api'; // Use environment variable
      const response = await axios.get<ArbitrageResponse>(`${API_BASE_URL}/arbitrage/`, { params });

      setOpportunities(response.data.opportunities.sort((a,b) => b.profit_margin_percentage - a.profit_margin_percentage));
      setLastRefreshed(new Date());

    } catch (err) {
      console.error("Error fetching arbitrage opportunities:", err);
      if (axios.isAxiosError(err) && err.response) {
         const errorDetail = err.response.data.detail;
         if (typeof errorDetail === 'string') {
            setError(errorDetail);
         } else if (errorDetail && typeof errorDetail.message === 'string') {
            setError(`${errorDetail.type || 'API Error'}: ${errorDetail.message}`);
         } else {
            setError("Could not fetch opportunities. Please check parameters or try again.");
         }
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
      setOpportunities([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDiscoverClick = () => {
    fetchOpportunities();
  };

  // Modal control functions
  const openCalculatorModal = (opportunity: ArbitrageOpportunity) => {
    setSelectedOpportunityForCalc(opportunity);
    // setTotalBetAmount('100'); // Optionally reset amount each time modal opens
    setIsModalOpen(true);
  };

  const closeCalculatorModal = () => {
    setIsModalOpen(false);
    setSelectedOpportunityForCalc(null); // Clear selected opportunity
    // setCalculatedStakes([]); // Optionally clear stakes
  };

  // Effect to calculate stakes
  useEffect(() => {
    if (!isModalOpen || !selectedOpportunityForCalc) {
      setCalculatedStakes([]);
      return;
    }

    const numericTotalAmount = parseFloat(totalBetAmount);
    if (isNaN(numericTotalAmount) || numericTotalAmount <= 0) {
      setCalculatedStakes([]);
      return;
    }

    const { best_outcome_odds, total_implied_odds } = selectedOpportunityForCalc;
    const newCalculatedStakes: CalculatedStakeInfo[] = [];

    if (total_implied_odds <= 0 || total_implied_odds >= 100) { // Sanity check, should be < 1 for arbs usually
        console.warn("Invalid total_implied_odds for calculation:", total_implied_odds, "Opportunity:", selectedOpportunityForCalc);
        setCalculatedStakes([]); // Clear or set an error state for stakes
        return;
    }

    for (const [outcomeName, [bookmakerName, odds]] of Object.entries(best_outcome_odds)) {
      if (odds <= 0) {
        console.warn(`Invalid odds for outcome ${outcomeName}: ${odds}`);
        continue;
      }
      // Stake_i = (TotalBetAmount * (1 / Odds_i)) / total_implied_odds
      const individualInvestmentRatio = (1 / odds) / total_implied_odds;
      const stake = numericTotalAmount * individualInvestmentRatio;
      const potentialReturn = stake * odds; // Should ideally be == numericTotalAmount / total_implied_odds

      newCalculatedStakes.push({
        outcomeName,
        bookmakerName,
        odds,
        stake,
        potentialReturn,
      });
    }
    setCalculatedStakes(newCalculatedStakes);

  }, [isModalOpen, selectedOpportunityForCalc, totalBetAmount]);


  return (
    <div className="flex flex-col min-h-screen bg-gray-100 dark:bg-slate-900 font-sans">
      {/* <Navbar /> */}

      <main className="flex-grow container mx-auto px-4 py-8 md:py-12">
        <header className="text-center mb-10 md:mb-12">
          <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-sky-500 to-green-400 dark:from-blue-500 dark:via-sky-400 dark:to-green-300 pb-2">
            Arbitrage Opportunities
          </h1>
          <p className="text-lg sm:text-xl text-gray-600 dark:text-gray-300 mt-3 max-w-2xl mx-auto">
            Discover risk-free betting opportunities by leveraging odds discrepancies across different bookmakers.
          </p>
        </header>

        {/* Filters Section */}
        <div className="mb-8 md:mb-12 p-6 bg-white dark:bg-slate-800 rounded-xl shadow-lg">
          <h2 className="text-xl font-semibold text-gray-700 dark:text-gray-200 mb-4">Filter Options</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
            <div>
              <label htmlFor="region" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Region</label>
              <select id="region" value={region} onChange={(e) => setRegion(e.target.value)} className="w-full p-2.5 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 focus:border-blue-500 dark:focus:border-sky-500 dark:bg-slate-700 dark:text-gray-100">
                {REGIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="cutoff" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Min. Profit % (e.g., 0.01 for 1%)</label>
              <input type="number" id="cutoff" value={cutoff} onChange={(e) => setCutoff(e.target.value)} min="0" max="0.99" step="0.001" placeholder="e.g., 0.01" className="w-full p-2.5 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 focus:border-blue-500 dark:focus:border-sky-500 dark:bg-slate-700 dark:text-gray-100"/>
            </div>
            <div>
              <label htmlFor="sports" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Sports (comma-separated keys)</label>
              <input type="text" id="sports" value={sports} onChange={(e) => setSports(e.target.value)} placeholder="e.g., soccer_epl,basketball_nba" className="w-full p-2.5 border border-gray-300 dark:border-slate-600 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 dark:focus:ring-sky-500 focus:border-blue-500 dark:focus:border-sky-500 dark:bg-slate-700 dark:text-gray-100"/>
            </div>
            <div className="flex items-center h-full pt-6 sm:pt-0">
              <input id="includeStartedMatches" type="checkbox" checked={includeStartedMatches} onChange={(e) => setIncludeStartedMatches(e.target.checked)} className="h-5 w-5 text-blue-600 dark:text-sky-500 border-gray-300 dark:border-slate-600 rounded focus:ring-blue-500 dark:focus:ring-sky-500 dark:bg-slate-700 dark:checked:bg-sky-500"/>
              <label htmlFor="includeStartedMatches" className="ml-2 text-sm text-gray-700 dark:text-gray-300">Include Started Matches</label>
            </div>
          </div>
        </div>

        <div className="text-center mb-8 md:mb-12">
          <button onClick={handleDiscoverClick} disabled={isLoading} className="px-8 py-3 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white font-semibold text-lg rounded-lg shadow-lg hover:shadow-xl transform transition-all duration-150 ease-in-out hover:scale-105 focus:outline-none focus:ring-4 focus:ring-sky-300 dark:focus:ring-sky-800 disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center mx-auto min-w-[250px]">
            {isLoading ? (<><svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Scanning...</>) : ('⚡ Discover Opportunities')}
          </button>
          {lastRefreshed && !isLoading && (<p className="text-xs text-gray-500 dark:text-gray-400 mt-2">Last refreshed: {timeAgo(lastRefreshed.toISOString())}</p>)}
        </div>

        {error && (<div className="mb-8 p-4 text-center text-red-700 dark:text-red-300 bg-red-100 dark:bg-red-900 dark:bg-opacity-40 rounded-lg shadow"><p><strong>Oops!</strong> {error}</p></div>)}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 md:gap-8">
          {isLoading && opportunities.length === 0 && hasSearched && ( Array.from({ length: 6 }).map((_, index) => <OpportunitySkeleton key={index} />))}
          {!isLoading && opportunities.length === 0 && hasSearched && !error && ( <div className="md:col-span-2 lg:col-span-3 text-center py-12"><svg className="mx-auto h-16 w-16 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg><h3 className="mt-2 text-xl font-semibold text-gray-700 dark:text-gray-200">No Opportunities Found</h3><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">There are no arbitrage opportunities matching your criteria. Try adjusting filters or discover again soon!</p></div>)}
          {!isLoading && !hasSearched && opportunities.length === 0 && !error && ( <div className="md:col-span-2 lg:col-span-3 text-center py-12"><h3 className="mt-2 text-xl font-semibold text-gray-700 dark:text-gray-200">Ready to find some Arbs?</h3><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Adjust your filters and click "Discover Opportunities" to start scanning.</p></div>)}

          {opportunities.map((op) => (
            <div
              key={op.match_id}
              className="bg-white dark:bg-slate-800 p-5 sm:p-6 rounded-xl shadow-lg hover:shadow-2xl transition-shadow duration-300 border border-transparent hover:border-sky-500 dark:hover:border-sky-400 flex flex-col justify-between"
            >
              <div> {/* Content wrapper */}
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h2 className="text-lg sm:text-xl font-semibold text-gray-800 dark:text-gray-100 leading-tight">{op.match_name}</h2>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {op.sport_title} - {new Date(op.match_start_time_iso).toLocaleString([], {year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'})}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      (Starts in {op.hours_to_start.toFixed(1)} hrs)
                    </p>
                  </div>
                  <span
                    className={`px-3 py-1 text-sm font-bold rounded-full text-white self-start whitespace-nowrap
                      ${op.profit_margin_percentage >= 3 ? 'bg-green-500 dark:bg-green-600' : op.profit_margin_percentage >= 1.5 ? 'bg-yellow-500 dark:bg-yellow-600' : 'bg-orange-500 dark:bg-orange-600'}`}
                  >
                    {op.profit_margin_percentage.toFixed(2)}%
                  </span>
                </div>

                <div className="space-y-2.5 mb-4">
                  {op.best_outcome_odds && Object.entries(op.best_outcome_odds).map(([outcomeName, [bookmakerName, odds]], index) => (
                      <div key={`${op.match_id}-outcome-${index}`} className="flex justify-between items-center p-3 bg-gray-50 dark:bg-slate-700/60 rounded-md text-sm">
                        <div>
                          <span className="font-medium text-gray-700 dark:text-gray-200">{outcomeName}</span>
                          <span className="block text-xs text-gray-500 dark:text-gray-400">{bookmakerName}</span>
                        </div>
                        <span className="font-semibold text-blue-600 dark:text-sky-400 text-base">{odds.toFixed(2)}</span>
                      </div>
                    ))}
                </div>
              </div> {/* End of content wrapper */}

              {/* Footer of the card */}
              <div className="mt-auto pt-3 border-t border-gray-100 dark:border-slate-700 flex justify-between items-center">
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  Implied Odds: {op.total_implied_odds.toFixed(4)}
                </p>
                <button
                  onClick={() => openCalculatorModal(op)}
                  className="px-4 py-1.5 bg-sky-500 hover:bg-sky-600 text-white text-xs font-semibold rounded-md shadow-sm transition-colors"
                >
                  Calculator
                </button>
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* MODAL FOR ARBITRAGE CALCULATOR */}
      <ArbitrageCalculatorModal
        isOpen={isModalOpen}
        onClose={closeCalculatorModal}
        opportunity={selectedOpportunityForCalc}
        totalAmount={totalBetAmount}
        onTotalAmountChange={setTotalBetAmount}
        stakes={calculatedStakes}
      />

      {/* <Footer /> */}
       {/* Tailwind CSS for modal animation (add to your global CSS or a <style> tag if not already present) */}
      <style jsx global>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes scaleUp {
          from { transform: scale(0.95); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }
        .animate-modalShow {
          animation: fadeIn 0.3s ease-out forwards, scaleUp 0.3s ease-out forwards;
        }
      `}</style>
    </div>
  );
}