import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import Chrome from "@/app/layout/Chrome";

export const metadata: Metadata = {
  title: "Sharper Bets — Data-driven sports betting analytics",
  description:
    "Live odds tracking, Dixon-Coles match predictions, lineup comparison, and arbitrage discovery — all in one platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-gray-50 dark:bg-slate-950 text-gray-900 dark:text-gray-100 antialiased">
        <AuthProvider>
          <Chrome>{children}</Chrome>
        </AuthProvider>
      </body>
    </html>
  );
}
