"use client";

import React, { useEffect, useState, useRef } from 'react';
import {
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  User,
  signOut,
} from 'firebase/auth';
import { auth } from "@/lib/firebaseConfig";
import { useRouter, usePathname } from 'next/navigation';

// Inline Google "G" mark. Kept here so the button is self-contained and doesn't
// pull in an icon dep just for the auth page.
function GoogleGlyph({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 18 18" className={className} aria-hidden>
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.616z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.836.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.707A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.961L3.964 7.293C4.672 5.166 6.656 3.58 9 3.58z"
      />
    </svg>
  );
}

const SignInButton: React.FC = () => {
  const router = useRouter();
  const pathname = usePathname();
  const [loading, setLoading] = useState<boolean>(false);
  const [user, setUser] = useState<User | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const isMounted = useRef(true);

  useEffect(() => {
    isMounted.current = true;

    if (!auth) {
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      if (!isMounted.current) return;
      setUser(currentUser);

      if (currentUser) {
        try {
          await currentUser.getIdToken();
          if (pathname === '/auth/login' || pathname === '/') {
            router.push('/dashboard');
          }
        } catch (error) {
          console.error("Error getting ID token:", error);
        }
      } else if (pathname?.startsWith('/dashboard')) {
        router.push('/auth/login');
      }
    });

    return () => {
      isMounted.current = false;
      unsubscribe();
    };
  }, [router, pathname]);

  const signInWithGoogle = async () => {
    if (!auth) return;
    setLoading(true);
    setErrorMsg(null);
    try {
      const provider = new GoogleAuthProvider();
      await signInWithPopup(auth, provider);
      // onAuthStateChanged handles the redirect.
    } catch (error: any) {
      const errorCode = error.code;
      let userFriendlyMessage = "An unexpected error occurred during sign-in.";
      if (errorCode === 'auth/popup-closed-by-user') {
        userFriendlyMessage = "Sign-in popup closed. Please try again.";
      } else if (errorCode === 'auth/cancelled-popup-request') {
        userFriendlyMessage = "Multiple sign-in popups attempted. Please try again.";
      } else if (error?.message) {
        userFriendlyMessage = `Sign-in failed: ${error.message}`;
      }
      setErrorMsg(userFriendlyMessage);
    } finally {
      if (isMounted.current) setLoading(false);
    }
  };

  const handleSignOut = async () => {
    if (!auth) return;
    setLoading(true);
    setErrorMsg(null);
    try {
      await signOut(auth);
      router.push('/auth/login');
    } catch (error) {
      console.error("Error signing out:", error);
      setErrorMsg("Failed to sign out. Please try again.");
    } finally {
      if (isMounted.current) setLoading(false);
    }
  };

  if (user) {
    return (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm text-gray-600 dark:text-gray-300">
          Signed in as <span className="font-semibold">{user.displayName || user.email}</span>
        </p>
        <button
          onClick={handleSignOut}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 transition-colors text-sm font-medium disabled:opacity-60"
        >
          {loading ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={signInWithGoogle}
        disabled={loading}
        className="
          group inline-flex items-center justify-center gap-3
          w-full h-12 px-5
          rounded-xl
          bg-white text-gray-700 dark:text-gray-800
          border border-gray-300
          shadow-sm
          hover:shadow-md hover:border-gray-400
          active:scale-[0.99]
          transition-all duration-150
          disabled:opacity-60 disabled:cursor-not-allowed
          font-medium
        "
        aria-label="Sign in with Google"
      >
        {loading ? (
          <span className="inline-flex items-center gap-2">
            <span className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
            Signing in…
          </span>
        ) : (
          <>
            <GoogleGlyph />
            <span>Sign in with Google</span>
          </>
        )}
      </button>

      {errorMsg && (
        <p className="text-sm text-red-600 dark:text-red-400 text-center" role="alert">
          {errorMsg}
        </p>
      )}
    </div>
  );
};

export default SignInButton;
