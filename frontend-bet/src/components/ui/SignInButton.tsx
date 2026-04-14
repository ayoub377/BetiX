"use client";

import React, { useEffect, useState, useRef } from 'react';
import {
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  User,
  signOut
} from 'firebase/auth';
import { auth } from "@/lib/firebaseConfig";
import { useRouter, usePathname } from 'next/navigation'; // usePathname is important here

interface SignInButtonProps {
  // You can add props here if needed
}

const SignInButton: React.FC<SignInButtonProps> = () => {
  const router = useRouter();
  const pathname = usePathname(); // Get the current path
  const [loading, setLoading] = useState<boolean>(false);
  const [user, setUser] = useState<User | null>(null);
  const isMounted = useRef(true);

  useEffect(() => {
    isMounted.current = true;

    if (!auth) {
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      if (!isMounted.current) {
        console.warn("SignInButton unmounted, skipping auth state change reaction.");
        return;
      }

      setUser(currentUser); // Update user state

      if (currentUser) {
        console.log('User signed in:', currentUser.email, "Current path:", pathname);
        try {
          const idToken = await currentUser.getIdToken();
          console.log('Firebase ID Token:', idToken);

          // Only redirect to dashboard if user is currently on login or root page
          if (pathname === '/auth/login' || pathname === '/') {
            console.log('Redirecting to /dashboard after sign-in...');
            router.push('/dashboard');
          }
          // If already on another page (e.g., /settings), no automatic redirect from here
        } catch (error) {
          console.error("Error getting ID token:", error);
        }
      } else { // currentUser is NULL (user is signed out)
        console.log('User signed out (onAuthStateChanged). Current path:', pathname);
        // If the user is ALREADY on a public page like login or home, DON'T redirect.
        // Only redirect if they signed out from a protected page.
        if (pathname?.startsWith('/dashboard')) { // Example: if they were on the dashboard
          console.log('User signed out from dashboard, redirecting to /auth/login...');
          router.push('/auth/login'); // Or your desired public page like '/'
        }
        // If pathname is /auth/login or /, no redirect here. User is correctly on a public page.
      }
    });

    return () => {
      isMounted.current = false;
      unsubscribe();
    };
  }, [router, pathname]); // Add pathname to the dependency array

  const signInWithGoogle = async () => {
    if (!auth) return;
    setLoading(true);
    try {
      const provider = new GoogleAuthProvider();
      const result = await signInWithPopup(auth, provider);
      console.log('Google Sign-In popup successful:', result.user.email);
      // onAuthStateChanged will handle the redirect based on the logic above
    } catch (error: any) {
      const errorCode = error.code;
      const errorMessage = error.message;
      console.error("Google Sign-In Error:", errorCode, errorMessage);

      let userFriendlyMessage = "An unexpected error occurred during sign-in.";
      if (errorCode === 'auth/popup-closed-by-user') {
        userFriendlyMessage = "Sign-in popup closed. Please try again.";
      } else if (errorCode === 'auth/cancelled-popup-request') {
        userFriendlyMessage = "Multiple sign-in popups attempted. Please try again.";
      } else if (errorMessage) {
        userFriendlyMessage = `Sign-in failed: ${errorMessage}`;
      }
      alert(userFriendlyMessage);
    } finally {
      if(isMounted.current) { // Guard state update
        setLoading(false);
      }
    }
  };

  const handleSignOut = async () => {
    if (!auth) return;
    setLoading(true);
    try {
      await signOut(auth);
      console.log('User signed out successfully by button click!');
      // After signOut, onAuthStateChanged will fire.
      // The logic in onAuthStateChanged will see currentUser as null.
      // If current path is already /auth/login, it won't redirect again.
      // Explicitly redirect to ensure user lands on login page after clicking sign out.
      router.push('/auth/login');
    } catch (error) {
      console.error("Error signing out:", error);
      alert("Failed to sign out. Please try again.");
    } finally {
      if(isMounted.current) { // Guard state update
        setLoading(false);
      }
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxWidth: '300px', margin: 'auto' }}>
      {user ? (
        <>
          <p>Welcome, {user.displayName || user.email}!</p>
          <button
            onClick={handleSignOut}
            style={{
              padding: '10px 20px',
              fontSize: '16px',
              backgroundColor: '#dc3545',
              color: 'white',
              border: 'none',
              borderRadius: '5px',
              cursor: 'pointer'
            }}
          >
            Sign Out
          </button>
        </>
      ) : (
        <button
          onClick={signInWithGoogle}
          disabled={loading}
          style={{
            padding: '10px 20px',
            fontSize: '16px',
            backgroundColor: '#4285F4',
            color: 'white',
            border: 'none',
            borderRadius: '5px',
            cursor: 'pointer',
            opacity: loading ? 0.7 : 1
          }}
        >
          {loading ? 'Signing In...' : 'Sign in with Google'}
        </button>
      )}
    </div>
  );
};

export default SignInButton;