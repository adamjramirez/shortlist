import type { Metadata } from "next";
import { Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Shortlist — AI Job Search",
  description: "Score and rank job listings with AI. Get a daily brief of your best matches.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${outfit.variable} ${jetbrains.variable} font-sans bg-gray-50 text-gray-900 antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
