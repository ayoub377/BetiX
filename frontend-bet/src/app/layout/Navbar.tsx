// src/app/layout/Navbar.tsx
"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { ChevronDown, ShieldCheck, Sparkles, UserCircle as UserAccountIcon, Zap } from "lucide-react";
import { clsx } from "clsx";

import { useAuth } from "@/contexts/AuthContext";
import Button from "@/components/ui/Button";
import { ThemeToggleButton } from "@/components/ui/ThemeToggleButton";

const MobileMenuIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" {...props}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-3.75 5.25h16.5" />
  </svg>
);

const SERVICE_LINKS = [
  { href: "/track", label: "Track a Match", description: "Start live odds tracking" },
  { href: "/odds", label: "Odds Tracker", description: "Live odds movement charts" },
  { href: "/pro-analysis", label: "Lineup Comparison", description: "Compare team rosters by position" },
  { href: "/predictions", label: "Match Predictions", description: "Dixon-Coles outcome probabilities" },
];

interface RoleBadgeProps {
  role: "normal" | "premium" | "admin";
}

function RoleBadge({ role }: RoleBadgeProps) {
  const config: Record<RoleBadgeProps["role"], { label: string; icon: React.ReactNode; className: string }> = {
    normal: {
      label: "Free",
      icon: null,
      className: "bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-300 border border-gray-200 dark:border-slate-600",
    },
    premium: {
      label: "Premium",
      icon: <Sparkles className="h-3 w-3" />,
      className: "bg-gradient-to-r from-sky-500 to-indigo-600 text-white shadow-sm",
    },
    admin: {
      label: "Admin",
      icon: <ShieldCheck className="h-3 w-3" />,
      className: "bg-gradient-to-r from-amber-500 to-rose-500 text-white shadow-sm",
    },
  };
  const c = config[role];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide",
        c.className,
      )}
    >
      {c.icon}
      {c.label}
    </span>
  );
}

export default function Navbar() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isMobileDropdownOpen, setIsMobileDropdownOpen] = useState(false);
  const [isDesktopDropdownOpen, setIsDesktopDropdownOpen] = useState(false);

  const router = useRouter();
  const pathname = usePathname();
  const { firebaseUser, isLoadingAuth, customUserProfile } = useAuth();
  const role = customUserProfile?.role ?? null;

  const handleSectionClick = (sectionId: string) => (e: React.MouseEvent<HTMLAnchorElement, MouseEvent>) => {
    if (pathname === "/") {
      e.preventDefault();
      const navbar = document.querySelector("#navbar");
      const element = document.getElementById(sectionId);
      if (element && navbar) {
        const offset = navbar.scrollHeight || 0;
        const bodyRect = document.body.getBoundingClientRect().top;
        const elementRect = element.getBoundingClientRect().top;
        const offsetPosition = elementRect - bodyRect - offset;
        window.scrollTo({ top: offsetPosition, behavior: "smooth" });
      }
    } else {
      router.push(`/#${sectionId}`);
    }
    setIsDesktopDropdownOpen(false);
    setIsMenuOpen(false);
  };

  // Close menus on route change
  useEffect(() => {
    setIsMenuOpen(false);
    setIsMobileDropdownOpen(false);
    setIsDesktopDropdownOpen(false);
  }, [pathname]);

  const isServicesActive = SERVICE_LINKS.some((s) => pathname === s.href || pathname.startsWith(s.href + "/"));
  const isHomeActive = pathname === "/";

  const desktopNavLinkBase =
    "px-3 py-2 rounded-md text-sm font-medium border-2 border-transparent transition-all duration-200 ease-in-out hover:bg-gray-100 dark:hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-sky-500 focus-visible:ring-opacity-75";
  const desktopNavInactive = "text-gray-600 dark:text-gray-300 hover:text-blue-600 dark:hover:text-sky-400";
  const desktopNavActive = "text-blue-600 dark:text-sky-400 bg-blue-50 dark:bg-sky-900/20";

  const desktopNavLinkStyles = (active: boolean) => clsx(desktopNavLinkBase, active ? desktopNavActive : desktopNavInactive);
  const desktopNavDropdownTriggerStyles = clsx(desktopNavLinkStyles(isServicesActive), "flex items-center gap-1 cursor-pointer");

  const handleAccountRedirect = useCallback(() => {
    if (isLoadingAuth) return;
    router.push(firebaseUser ? "/dashboard" : "/auth/login");
    setIsMenuOpen(false);
  }, [firebaseUser, isLoadingAuth, router]);

  return (
    <nav
      id="navbar"
      className="bg-white/95 dark:bg-slate-900/95 backdrop-blur supports-[backdrop-filter]:bg-white/75 dark:supports-[backdrop-filter]:bg-slate-900/75 text-gray-700 dark:text-gray-300 shadow-sm sticky top-0 left-0 w-full z-50 border-b border-gray-200 dark:border-slate-700"
    >
      <div className="container mx-auto flex items-center justify-between p-4">
        <div className="flex items-center gap-8">
          <Link href="/" aria-label="Go to homepage" onClick={() => setIsMenuOpen(false)} className="flex items-center gap-2">
            <img src="/assets/logo-saas.jpg" alt="Sharper Bets logo" className="w-auto h-10 md:h-12 rounded-md" />
            <span className="hidden sm:inline-block text-base font-bold text-gray-800 dark:text-gray-100">
              Sharper Bets
            </span>
          </Link>

          <div className="hidden md:flex items-center space-x-1">
            <Link href="/" className={desktopNavLinkStyles(isHomeActive)}>
              Home
            </Link>

            <div
              className="relative group"
              onMouseEnter={() => setIsDesktopDropdownOpen(true)}
              onMouseLeave={() => setTimeout(() => setIsDesktopDropdownOpen(false), 150)}
            >
              <button
                onClick={() => setIsDesktopDropdownOpen((open) => !open)}
                className={desktopNavDropdownTriggerStyles}
                aria-expanded={isDesktopDropdownOpen}
                aria-haspopup="menu"
              >
                Services{" "}
                <ChevronDown
                  className={clsx("transition-transform duration-150", { "rotate-180": isDesktopDropdownOpen })}
                  size={16}
                />
              </button>
              <div className="absolute left-0 top-full w-2 h-2 bg-transparent pointer-events-none" />
              <div
                className={clsx(
                  "absolute left-0 mt-1 w-72 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 rounded-xl shadow-xl py-2 border border-gray-100 dark:border-slate-700",
                  "transition-all duration-200 origin-top-left",
                  !isDesktopDropdownOpen && "opacity-0 scale-95 pointer-events-none",
                  isDesktopDropdownOpen && "opacity-100 scale-100",
                )}
                role="menu"
                onMouseEnter={() => setIsDesktopDropdownOpen(true)}
              >
                {SERVICE_LINKS.map((s) => {
                  const active = pathname === s.href;
                  return (
                    <Link
                      key={s.href}
                      href={s.href}
                      role="menuitem"
                      className={clsx(
                        "block py-2 px-4 transition-colors text-sm",
                        active
                          ? "bg-blue-50 dark:bg-sky-900/20 text-blue-700 dark:text-sky-300"
                          : "hover:bg-gray-50 dark:hover:bg-slate-700/60",
                      )}
                    >
                      <div className="font-medium">{s.label}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{s.description}</div>
                    </Link>
                  );
                })}
              </div>
            </div>

            <Link href="/pricing" className={desktopNavLinkStyles(pathname === "/pricing")}>
              Pricing
            </Link>
            <a href="/#about" onClick={handleSectionClick("about")} className={desktopNavLinkStyles(false)}>
              About
            </a>
            <a href="/#faq" onClick={handleSectionClick("faq")} className={desktopNavLinkStyles(false)}>
              FAQ
            </a>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {firebaseUser && role && <RoleBadge role={role} />}
          <ThemeToggleButton />
          {!firebaseUser && !isLoadingAuth && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => router.push("/auth/login")}
              className="hidden sm:inline-flex"
              leftIcon={<Zap className="h-4 w-4" />}
            >
              Sign in
            </Button>
          )}
          {firebaseUser && (
            <Button
              variant="ghost"
              size="icon"
              onClick={handleAccountRedirect}
              disabled={isLoadingAuth}
              aria-label="Open dashboard"
            >
              <UserAccountIcon className="h-6 w-6" />
            </Button>
          )}
          <div className="md:hidden">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              aria-label="Toggle mobile menu"
            >
              <MobileMenuIcon className="h-6 w-6" />
            </Button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {isMenuOpen && (
        <div className="md:hidden bg-white dark:bg-slate-800 w-full absolute left-0 top-full shadow-lg border-t border-gray-200 dark:border-slate-700">
          <div className="flex flex-col p-4 space-y-1">
            <Link
              href="/"
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700"
              onClick={() => setIsMenuOpen(false)}
            >
              Home
            </Link>
            <Button
              variant="ghost"
              onClick={() => setIsMobileDropdownOpen(!isMobileDropdownOpen)}
              rightIcon={
                <ChevronDown
                  className={clsx("transition-transform", { "rotate-180": isMobileDropdownOpen })}
                  size={18}
                />
              }
              className="cursor-pointer text-left text-base font-medium text-gray-700 dark:text-gray-200 py-2 px-3 hover:!bg-gray-100 dark:hover:!bg-slate-700 rounded-md"
            >
              Services
            </Button>
            {isMobileDropdownOpen && (
              <div className="ml-4 mt-1 pt-1 border-l border-gray-200 dark:border-slate-700 pl-3 flex flex-col">
                {SERVICE_LINKS.map((s) => (
                  <Link
                    key={s.href}
                    href={s.href}
                    className="block px-3 py-2 rounded-md text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
                    onClick={() => setIsMenuOpen(false)}
                  >
                    {s.label}
                  </Link>
                ))}
              </div>
            )}
            <Link
              href="/pricing"
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700"
              onClick={() => setIsMenuOpen(false)}
            >
              Pricing
            </Link>
            <a
              href="/#about"
              onClick={(e) => handleSectionClick("about")(e)}
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700"
            >
              About
            </a>
            <a
              href="/#faq"
              onClick={(e) => handleSectionClick("faq")(e)}
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700"
            >
              FAQ
            </a>
            <div className="pt-3 mt-2 border-t border-gray-200 dark:border-slate-700 flex items-center gap-2">
              {firebaseUser && role && <RoleBadge role={role} />}
              <Button
                variant="ghost"
                onClick={handleAccountRedirect}
                disabled={isLoadingAuth}
                leftIcon={<UserAccountIcon className="w-5 h-5" />}
                className="cursor-pointer flex-1 justify-start text-base font-medium"
              >
                {isLoadingAuth ? "Loading..." : firebaseUser ? "Dashboard" : "Sign in"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
