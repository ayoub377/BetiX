import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import Chrome from "@/app/layout/Chrome";

export const metadata: Metadata = {
  title: "Sharper Bets — Data-driven sports betting analytics",
  description:
    "Live odds tracking, Dixon-Coles match predictions, and lineup comparison — all in one platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning is required by next-themes — it sets the
    // `class` attribute on <html> client-side, which would otherwise diff
    // against the SSR output and trigger a console warning.
    <html lang="en" suppressHydrationWarning>
      <body className="bg-gray-50 dark:bg-slate-950 text-gray-900 dark:text-gray-100 antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <AuthProvider>
            <Chrome>{children}</Chrome>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
