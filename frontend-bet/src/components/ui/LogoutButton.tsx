// src/components/ui/LogoutButton.tsx (Create this new file)
"use client";

import React from 'react';
import { LogOut as LogOutIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
// Assuming your AuthContext handles user state updates on sign-out
// We'll use the direct Firebase signOut function here.
import { signOut as firebaseSignOut } from 'firebase/auth';
import { auth as firebaseAuthInstance } from '@/lib/firebaseConfig'; // Your Firebase auth instance

interface LogoutButtonProps {
  className?: string; // Optional custom Tailwind classes for the button
  iconClassName?: string; // Optional custom classes for the icon
  text?: string; // Optional text for the button, defaults to "Logout"
  showText?: boolean; // Whether to show text next to the icon
  onLogout?: () => void; // Optional callback after logout attempt
}

const LogoutButton: React.FC<LogoutButtonProps> = ({
  className,
  iconClassName,
  text = "Logout",
  showText = false,
  onLogout,
}) => {
  const router = useRouter();

  // Default styling similar to your header example, can be overridden by props
  const defaultButtonClassName = "p-2.5 rounded-full hover:bg-red-100 dark:hover:bg-red-800/50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:focus:ring-offset-gray-900 group transition-colors flex items-center";
  const defaultIconClassName = "h-5 w-5 text-red-600 dark:text-red-400 group-hover:text-red-500 dark:group-hover:text-red-300";

  const handleLogout = async () => {
    try {
      if (!firebaseAuthInstance) return;
      await firebaseSignOut(firebaseAuthInstance);
      // The AuthContext's onAuthStateChanged listener should automatically update
      // global user state (firebaseUser, customUserProfile, isProUser) to null/false.
      console.log('User signed out successfully.');
      router.push('/auth'); // Redirect to login page or home page
      if (onLogout) {
        onLogout();
      }
    } catch (error) {
      console.error("Error signing out:", error);
      // You might want to show a user-facing error message here
    }
  };

  return (
    <button
      onClick={handleLogout}
      className={className !== undefined ? className : defaultButtonClassName}
      aria-label={text}
    >
      <LogOutIcon className={iconClassName !== undefined ? iconClassName : defaultIconClassName} />
      {showText && <span className={showText && text ? "ml-2" : ""}>{text}</span>}
    </button>
  );
};

export default LogoutButton;