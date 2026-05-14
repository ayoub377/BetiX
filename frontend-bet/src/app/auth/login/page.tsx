import Image from "next/image";
import Link from "next/link";
import SignInButton from "@/components/ui/SignInButton";

export default function LoginPage() {
  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-slate-50 via-sky-50 to-indigo-50 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950/30">
      {/* Top bar — brand only, no global nav */}
      <header className="px-6 py-5">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-gray-800 dark:text-gray-100 hover:opacity-80 transition-opacity"
        >
          <span className="inline-flex items-center justify-center h-9 w-9 rounded-lg bg-gradient-to-br from-sky-500 to-indigo-600 text-white font-bold shadow-md">
            SB
          </span>
          <span className="font-semibold text-base">Sharper Bets</span>
        </Link>
      </header>

      {/* Hero + form */}
      <main className="flex-1 flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-5xl grid lg:grid-cols-2 gap-10 items-center">
          {/* Marketing / hero panel */}
          <section className="hidden lg:flex flex-col gap-6 pr-8">
            <div className="inline-flex items-center gap-2 self-start px-3 py-1 rounded-full bg-white/70 dark:bg-slate-800/60 border border-gray-200 dark:border-slate-700 text-xs font-medium text-gray-700 dark:text-gray-200 shadow-sm backdrop-blur">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Live odds tracking
            </div>
            <h2 className="text-4xl xl:text-5xl font-bold tracking-tight text-gray-900 dark:text-gray-50 leading-tight">
              Find value the bookmakers miss.
            </h2>
            <p className="text-base text-gray-600 dark:text-gray-300 leading-relaxed max-w-md">
              Track live odds movement, compare against sharp lines, and surface
              arbitrage opportunities — all in one place.
            </p>

            <div className="relative mt-2">
              <div className="absolute inset-0 bg-gradient-to-tr from-sky-200/40 to-indigo-200/40 dark:from-sky-900/40 dark:to-indigo-900/40 rounded-2xl blur-2xl" />
              <div className="relative rounded-2xl overflow-hidden border border-gray-200 dark:border-slate-700 shadow-xl bg-white dark:bg-slate-800">
                <Image
                  src="/sharper-bets-banner.png"
                  alt="Sharper Bets dashboard preview"
                  width={720}
                  height={360}
                  priority
                  className="w-full h-auto object-cover"
                />
              </div>
            </div>

            <ul className="grid grid-cols-2 gap-3 text-sm text-gray-600 dark:text-gray-300 mt-2">
              <li className="flex items-center gap-2">
                <Check /> Live odds polling
              </li>
              <li className="flex items-center gap-2">
                <Check /> Arbitrage detection
              </li>
              <li className="flex items-center gap-2">
                <Check /> Dixon-Coles predictions
              </li>
              <li className="flex items-center gap-2">
                <Check /> Soccer &amp; tennis
              </li>
            </ul>
          </section>

          {/* Sign-in card */}
          <section className="w-full max-w-md mx-auto lg:mx-0">
            <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl border border-gray-200 dark:border-slate-700 p-8 sm:p-10">
              {/* Logo + heading */}
              <div className="flex flex-col items-center text-center mb-7">
                <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 text-white text-xl font-bold shadow-md mb-4">
                  SB
                </div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50">
                  Welcome back
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1.5">
                  Sign in to your Sharper Bets account
                </p>
              </div>

              {/* Auth provider */}
              <SignInButton />

              {/* Divider + reassurance copy */}
              <div className="mt-7 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
                <span className="flex-1 h-px bg-gray-200 dark:bg-slate-700" />
                <span>secure sign-in via Google</span>
                <span className="flex-1 h-px bg-gray-200 dark:bg-slate-700" />
              </div>

              <p className="mt-6 text-xs text-gray-500 dark:text-gray-400 text-center leading-relaxed">
                By signing in, you agree to our{" "}
                <Link href="/terms" className="text-sky-600 dark:text-sky-400 hover:underline">
                  Terms
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="text-sky-600 dark:text-sky-400 hover:underline">
                  Privacy Policy
                </Link>
                .
              </p>
            </div>

            <p className="text-sm text-gray-500 dark:text-gray-400 text-center mt-5">
              <Link href="/" className="hover:text-gray-700 dark:hover:text-gray-200 inline-flex items-center gap-1">
                <span aria-hidden>←</span> Back to home
              </Link>
            </p>
          </section>
        </div>
      </main>

      {/* Slim footer — auth pages stay free of the global chrome */}
      <footer className="px-6 py-5 border-t border-gray-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 backdrop-blur">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
          <span>&copy; {new Date().getFullYear()} Sharper Bets. All rights reserved.</span>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="hover:text-gray-700 dark:hover:text-gray-200">
              Terms
            </Link>
            <Link href="/privacy" className="hover:text-gray-700 dark:hover:text-gray-200">
              Privacy
            </Link>
            <Link href="/" className="hover:text-gray-700 dark:hover:text-gray-200">
              Home
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

function Check() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className="h-4 w-4 text-emerald-500 flex-shrink-0"
      aria-hidden
    >
      <path
        fillRule="evenodd"
        d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.42 0l-3.5-3.5a1 1 0 011.42-1.42L8.5 12.08l6.79-6.79a1 1 0 011.414 0z"
        clipRule="evenodd"
      />
    </svg>
  );
}
