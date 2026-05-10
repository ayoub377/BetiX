"use client";

import React from "react";
import { usePathname } from "next/navigation";

import Navbar from "@/app/layout/Navbar";
import Footer from "@/app/layout/Footer";

// Routes where the marketing chrome is suppressed:
//   - /auth/*       — login screens render their own minimal layout
//   - /billing/*    — post-checkout flow needs a clean confirmation screen
const HIDE_PREFIXES = ["/auth", "/billing"];

export default function Chrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hideChrome = HIDE_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));

  if (hideChrome) {
    return <>{children}</>;
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
