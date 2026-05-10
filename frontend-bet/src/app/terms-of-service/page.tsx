import React from "react";

export const metadata = {
  title: "Terms of Service — Sharper Bets",
};

export default function TermsOfServicePage() {
  const updated = "May 2026";

  return (
    <div className="container mx-auto px-4 py-16 max-w-3xl">
      <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50 mb-2">
        Terms of Service
      </h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-8">Last updated: {updated}</p>

      <div className="prose prose-sm dark:prose-invert max-w-none space-y-6 text-gray-700 dark:text-gray-300">
        <p className="text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 rounded-lg p-4 text-sm">
          <strong>Note:</strong> this is a placeholder while we finalise our legal review. The
          summary below reflects how the platform operates today. For questions, email{" "}
          <a href="mailto:hello@sharperbets.app" className="font-medium underline">
            hello@sharperbets.app
          </a>
          .
        </p>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">1. The service</h2>
          <p>
            Sharper Bets provides analytical tools — live odds tracking, statistical match
            predictions, lineup comparison, and arbitrage discovery — for sports-betting
            decision support. We do not place bets on your behalf and we do not guarantee
            outcomes. All betting decisions are yours.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">2. Eligibility</h2>
          <p>
            You must be at least 18 years old (or the legal gambling age in your jurisdiction,
            whichever is higher) and legally permitted to use sports-betting services where you
            live. We don't sell bets — but our tools are intended for adults who legally engage
            with regulated bookmakers.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">3. Subscriptions and billing</h2>
          <p>
            Premium is a recurring monthly subscription billed by LemonSqueezy. You can cancel
            anytime through the customer portal linked from your dashboard. Cancellation takes
            effect at the end of your current billing period; we don't pro-rate refunds.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">4. Acceptable use</h2>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>One account per person. Sharing accounts is grounds for suspension.</li>
            <li>Don't reverse-engineer the API or scrape it at volumes that bypass tier limits.</li>
            <li>Don't republish our predictions or odds data as if they were your own.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">5. No warranty</h2>
          <p>
            The service is provided "as is." Statistical predictions are educational tools, not
            financial advice. We're not liable for losses incurred from bets you place based on
            our outputs. Bet responsibly.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">6. Termination</h2>
          <p>
            You can delete your account anytime by emailing us. We can suspend or terminate
            accounts that violate these terms, with refund of any unused subscription period.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">7. Changes</h2>
          <p>
            We may update these terms occasionally. Material changes will be announced on the
            site or by email at least 14 days before they take effect.
          </p>
        </section>
      </div>
    </div>
  );
}
