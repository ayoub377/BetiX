import React from "react";

export const metadata = {
  title: "Privacy Policy — Sharper Bets",
};

export default function PrivacyPolicyPage() {
  const updated = "May 2026";

  return (
    <div className="container mx-auto px-4 py-16 max-w-3xl">
      <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50 mb-2">
        Privacy Policy
      </h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-8">Last updated: {updated}</p>

      <div className="prose prose-sm dark:prose-invert max-w-none space-y-6 text-gray-700 dark:text-gray-300">
        <p className="text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 rounded-lg p-4 text-sm">
          <strong>Note:</strong> this is a placeholder while we finalise our legal review. The
          summary below reflects how the platform actually behaves today, but isn't a substitute
          for a lawyer-reviewed policy. If you need clarification, email{" "}
          <a href="mailto:hello@sharperbets.app" className="font-medium underline">
            hello@sharperbets.app
          </a>
          .
        </p>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">What we collect</h2>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>Account data: email, display name, and any profile fields you provide (via Firebase Authentication).</li>
            <li>Usage data: which pages you visit, which API endpoints you call, and how often (so we can enforce per-tier quotas).</li>
            <li>Payment data: handled by LemonSqueezy. We never see or store credit card numbers.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">How we use it</h2>
          <ul className="list-disc pl-6 space-y-1 mt-2">
            <li>To run the service: authenticate you, enforce quotas, deliver predictions and odds data.</li>
            <li>To bill you (if you subscribe to Premium).</li>
            <li>To debug issues. We do not sell or share your data with third parties for advertising.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">Cookies</h2>
          <p>
            We use a Firebase auth cookie to keep you signed in and a theme preference cookie to
            remember dark mode. No third-party tracking or advertising cookies.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">Your rights</h2>
          <p>
            You can request a copy of your data, ask us to delete your account, or export your
            tracked-match history at any time by emailing the address above.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-50">Where data lives</h2>
          <p>
            User and subscription data are stored in PostgreSQL on Google Cloud (europe-west9).
            Live odds snapshots are cached in Redis. Authentication is handled by Firebase
            Authentication. Payments are processed by LemonSqueezy.
          </p>
        </section>
      </div>
    </div>
  );
}
