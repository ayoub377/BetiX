// src/components/layout/Navbar.tsx
"use client"
import React, {useEffect, useState, useCallback} from "react";
// 👇 Corrected imports for App Router
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import {ChevronDown, UserCircle as UserAccountIcon} from "lucide-react";
import {clsx} from "clsx";
import { useAuth } from "@/contexts/AuthContext";
import Button from "@/components/ui/Button";
import { ThemeToggleButton } from "@/components/ui/ThemeToggleButton";

const LogoutIcon = (props: React.SVGProps<SVGSVGElement>) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} {...props} >
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
    </svg>
);

const MobileMenuIcon = (props: React.SVGProps<SVGSVGElement>) => (
    <svg fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" {...props}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-3.75 5.25h16.5" />
    </svg>
);

export default function Navbar() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const [isMobileDropdownOpen, setIsMobileDropdownOpen] = useState(false);
    const [isDesktopDropdownOpen, setIsDesktopDropdownOpen] = useState(false);

    const router = useRouter(); // From next/navigation
    const pathname = usePathname(); // From next/navigation
    const { firebaseUser, isLoadingAuth } = useAuth();

    const handleSectionClick = (sectionId: string) => (e: React.MouseEvent<HTMLAnchorElement, MouseEvent>) => {
        if (pathname === '/') { // Use pathname from usePathname()
            e.preventDefault();
            const navbar = document.querySelector('#navbar');
            const element = document.getElementById(sectionId);

            if (element && navbar) {
                const offset = navbar.scrollHeight || 0;
                const bodyRect = document.body.getBoundingClientRect().top;
                const elementRect = element.getBoundingClientRect().top;
                const elementPosition = elementRect - bodyRect;
                const offsetPosition = elementPosition - offset;

                window.scrollTo({
                    top: offsetPosition,
                    behavior: 'smooth'
                });
            }
        } else {
            router.push(`/#${sectionId}`); // router from next/navigation
        }
        setIsDesktopDropdownOpen(false);
        setIsMenuOpen(false);
    };

    // Close menus on route change using pathname from usePathname()
    useEffect(() => {
        setIsMenuOpen(false);
        setIsMobileDropdownOpen(false);
        setIsDesktopDropdownOpen(false);
    }, [pathname]); // Trigger when pathname changes

  const desktopNavLinkStyles = "px-3 py-2 rounded-md text-sm font-medium text-gray-600 dark:text-gray-300 border-2 border-transparent transition-all duration-200 ease-in-out hover:text-blue-600 dark:hover:text-sky-400 hover:bg-gray-100 dark:hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-sky-500 focus-visible:ring-opacity-75";
  const desktopNavDropdownTriggerStyles = `${desktopNavLinkStyles} flex items-center gap-1 cursor-pointer`;

  const handleAccountRedirect = useCallback(() => {
    if (isLoadingAuth) return;

    if (firebaseUser) {
      router.push('/dashboard'); // router from next/navigation
    } else {
      router.push('/auth/login'); // router from next/navigation
    }
    setIsMenuOpen(false);
  }, [firebaseUser, isLoadingAuth, router]);


    return (
        <nav id="navbar" className="bg-gradient-to-b from-white to-gray-50 dark:from-slate-900 dark:to-slate-800 text-gray-700 dark:text-gray-300 shadow-sm fixed top-0 left-0 w-full z-50 border-b border-gray-200 dark:border-slate-700">
            <div className="container mx-auto flex items-center justify-between p-4">
                 <div className="flex items-center gap-8">
                    <Link href="/" aria-label="Go to homepage" onClick={() => setIsMenuOpen(false)}>
                        <img src="/assets/logo-saas.jpg" alt="Sharper Bets logo" className="w-auto h-12 md:h-14"/>
                    </Link>

                    <div className="hidden md:flex items-center space-x-1">
                        <Link href="/" className={desktopNavLinkStyles}>
                            Home
                        </Link>

                        <div
                            className="relative group"
                            onMouseEnter={() => setIsDesktopDropdownOpen(true)}
                            onMouseLeave={() => setTimeout(() => setIsDesktopDropdownOpen(false), 200)}
                        >
                            <button
                                onClick={(e) => {
                                    if (pathname === '/') { // Use pathname
                                        e.preventDefault();
                                        const clickEvent = e as unknown as React.MouseEvent<HTMLAnchorElement, MouseEvent>;
                                        handleSectionClick('services')(clickEvent);
                                    } else {
                                        router.push('/#services'); // Use router from next/navigation
                                    }
                                }}
                                className={desktopNavDropdownTriggerStyles}
                                aria-expanded={isDesktopDropdownOpen}
                            >
                                Services <ChevronDown
                                className={clsx('transition-transform duration-150 text-gray-500 dark:text-gray-400 group-hover:text-blue-600 dark:group-hover:text-sky-400', {'rotate-180': isDesktopDropdownOpen})}
                                size={16}
                            />
                            </button>
                            <div className="absolute left-0 top-full w-full h-4 bg-transparent pointer-events-none"/>
                            <div className={clsx(
                                'absolute left-0 mt-0 w-56 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 rounded-lg shadow-xl py-2 border border-gray-100 dark:border-slate-700',
                                'transition-all duration-300 origin-top',
                                !isDesktopDropdownOpen && 'opacity-0 scale-95 pointer-events-none',
                                isDesktopDropdownOpen && 'opacity-100 scale-100'
                            )}
                            onMouseEnter={() => setIsDesktopDropdownOpen(true)}
                            >
                                <Link href="/pro-analysis" className="block py-2 px-4 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400 rounded-md transition-colors text-sm">
                                    Lineup Comparison
                                </Link>
                                <Link href="/arbitrage" className="block py-2 px-4 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400 rounded-md transition-colors text-sm">
                                    Arbitrage Opportunities
                                </Link>
                                <Link href="/odds" className="block py-2 px-4 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400 rounded-md transition-colors text-sm">
                                    Odds Tracker
                                </Link>
                            </div>
                        </div>

                        <Link href="/#about" onClick={handleSectionClick('about')} className={desktopNavLinkStyles}>About</Link>
                        <Link href="/#faq" onClick={handleSectionClick('faq')} className={desktopNavLinkStyles}>FAQ</Link>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <ThemeToggleButton />
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={handleAccountRedirect}
                        disabled={isLoadingAuth}
                        className="text-gray-600 dark:text-gray-400 hover:!bg-gray-100 dark:hover:!bg-slate-700 focus-visible:!ring-blue-500 dark:focus-visible:!ring-sky-500"
                        aria-label="User account"
                    >
                        {isLoadingAuth ? (
                            <div className="h-6 w-6 animate-pulse bg-gray-300 dark:bg-gray-600 rounded-full" />
                        ) : (
                            <UserAccountIcon className="h-6 w-6" />
                        )}
                    </Button>
                    <div className="md:hidden">
                        <Button variant="ghost" size="icon" onClick={() => setIsMenuOpen(!isMenuOpen)} className="text-gray-600 dark:text-gray-400 hover:!bg-gray-100 dark:hover:!bg-slate-700 focus-visible:!ring-blue-500 dark:focus-visible:!ring-sky-500" aria-label="Toggle mobile menu">
                            <MobileMenuIcon className="h-6 w-6"/>
                        </Button>
                    </div>
                </div>
            </div>

            {isMenuOpen && (
                <div className="md:hidden bg-white dark:bg-slate-800 w-full absolute left-0 top-full shadow-lg border-t border-gray-200 dark:border-slate-700">
                     <div className="flex flex-col p-4 space-y-2">
                        <Link href="/" className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={() => setIsMenuOpen(false)}>Home</Link>
                        <div className="">
                            <Button
                                variant="ghost"
                                onClick={() => setIsMobileDropdownOpen(!isMobileDropdownOpen)}
                                rightIcon={<ChevronDown className={clsx('transition-transform text-gray-500 dark:text-gray-400', {'rotate-180': isMobileDropdownOpen})} size={20} />}
                                // 👇 MODIFIED HERE: Added text-left, text-base, font-medium for consistency
                                className="cursor-pointer text-left text-base font-medium text-gray-700 dark:text-gray-200 py-2 px-3 hover:!bg-gray-100 dark:hover:!bg-slate-700 hover:!text-blue-600 dark:hover:!text-sky-400 rounded-md"
                                aria-expanded={isMobileDropdownOpen}
                            >
                                Services
                            </Button>
                            {isMobileDropdownOpen && (
                                <div className="ml-4 mt-2 pt-2 border-l border-gray-200 dark:border-slate-700 pl-3 flex flex-col space-y-1">
                                    <Link href="/pro-analysis" className="block px-3 py-2 rounded-md text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={() => setIsMenuOpen(false)}>Lineup Comparison</Link>
                                    <Link href="/arbitrage" className="block px-3 py-2 rounded-md text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={() => setIsMenuOpen(false)}>Arbitrage Opportunities</Link>
                                    <Link href="/odds" className="block px-3 py-2 rounded-md text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={() => setIsMenuOpen(false)}>Odds Tracker</Link>
                                </div>
                            )}
                        </div>
                        <Link href="/#about" className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={(e) => { handleSectionClick('about')(e); }}>About</Link>
                        <Link href="/#faq" className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-sky-400" onClick={(e) => { handleSectionClick('faq')(e); }}>FAQ</Link>
                        <div className="pt-4 mt-2 border-t border-gray-200 dark:border-slate-700">
                            <Button
                                variant="ghost"
                                onClick={handleAccountRedirect}
                                disabled={isLoadingAuth}
                                leftIcon={isLoadingAuth ? undefined : <UserAccountIcon className="w-5 h-5 text-gray-600 dark:text-gray-300" />}
                                className="cursor-pointer w-full justify-start text-base font-medium text-gray-700 dark:text-gray-200 py-2 px-3 hover:!bg-gray-100 dark:hover:!bg-slate-700 hover:!text-blue-600 dark:hover:!text-sky-400 rounded-md"
                            >
                                {isLoadingAuth ? "Loading..." : (firebaseUser ? "My Account / Dashboard" : "Login / Sign Up")}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </nav>
    );
}