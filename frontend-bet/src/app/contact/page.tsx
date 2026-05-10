import React from "react";
import { Mail } from "lucide-react";

export const metadata = {
  title: "Contact — Sharper Bets",
};

export default function ContactPage() {
  return (
    <div className="container mx-auto px-4 py-16 max-w-2xl">
      <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-gray-50 mb-2">
        Contact
      </h1>
      <p className="text-gray-600 dark:text-gray-400 mb-8">
        Questions, feedback, or bug reports — we read everything.
      </p>

      <div className="bg-white dark:bg-slate-800 rounded-2xl border border-gray-200 dark:border-slate-700 p-6 sm:p-8">
        <div className="flex items-start gap-4">
          <div className="flex-shrink-0 inline-flex items-center justify-center h-12 w-12 rounded-xl bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400">
            <Mail className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-1">
              Email us
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
              The fastest way to reach us. We typically reply within 24 hours.
            </p>
            <a
              href="mailto:hello@sharperbets.app"
              className="inline-flex items-center gap-1.5 text-sky-600 dark:text-sky-400 font-medium hover:underline"
            >
              hello@sharperbets.app
            </a>
          </div>
        </div>
      </div>

      <p className="mt-8 text-sm text-gray-500 dark:text-gray-400">
        For account or billing issues, please mention the email address you signed up with.
      </p>
    </div>
  );
}
