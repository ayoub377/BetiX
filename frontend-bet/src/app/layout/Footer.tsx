// src/components/layout/Footer.tsx
import React from 'react';
import Link from 'next/link';
// You can import an SVG logo component or use an <img> tag
// import Logo from '@/components/ui/Logo'; // Example if you have a Logo component

const Footer: React.FC = () => {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-gray-100 dark:bg-slate-800 border-t border-gray-200 dark:border-slate-700">
      <div className="container mx-auto px-6 py-12 lg:py-16">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
          {/* Logo and About Section */}
          <div className="md:col-span-4 lg:col-span-5">
            <Link href="/" className="inline-block mb-4" aria-label="Go to homepage">
              {/* Assuming you use the same image logo. If you have an SVG component, use that. */}
              <img src="/assets/logo-saas.jpg" alt="Sharper Bets Logo" className="h-12 md:h-14 w-auto" />
              {/* <Logo className="h-10 text-blue-600 dark:text-sky-500" /> // Example if Logo is an SVG component */}
            </Link>
            <p className="text-gray-600 dark:text-gray-400 text-sm leading-relaxed max-w-sm">
              Sharper Bets provides cutting-edge analytics and tools to give you a competitive edge.
              Empowering your decisions with data-driven insights.
            </p>
          </div>

          {/* Spacer on medium screens */}
          <div className="hidden md:block md:col-span-1 lg:col-span-1"></div>

          {/* Navigation Links */}
          <div className="md:col-span-7 lg:col-span-6 grid grid-cols-2 sm:grid-cols-3 gap-8">
            <div>
              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-200 tracking-wider uppercase mb-3">Product</h5>
              <ul className="space-y-2">
                <li><Link href="/#services" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">Features</Link></li>
                <li><Link href="/pricing" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">Pricing</Link></li>
                <li><Link href="/#faq" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">FAQ</Link></li>
                {/* Add more product links if needed */}
              </ul>
            </div>
            <div>
              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-200 tracking-wider uppercase mb-3">Company</h5>
              <ul className="space-y-2">
                <li><Link href="/#about" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">About Us</Link></li>
                <li><Link href="/contact" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">Contact</Link></li>
              </ul>
            </div>
            <div>
              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-200 tracking-wider uppercase mb-3">Legal</h5>
              <ul className="space-y-2">
                <li><Link href="/privacy-policy" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">Privacy Policy</Link></li>
                <li><Link href="/terms-of-service" className="text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-sky-400 transition-colors text-sm">Terms of Service</Link></li>
                {/* Add more legal links if needed */}
              </ul>
            </div>
          </div>
        </div>

        {/* Copyright Section */}
        <div className="mt-10 lg:mt-12 pt-8 border-t border-gray-200 dark:border-slate-700 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            &copy; {currentYear} Sharper Bets. All rights reserved.
          </p>
          {/* Optional: Add a small message or social links here */}
        </div>
      </div>
    </footer>
  );
};

export default Footer;