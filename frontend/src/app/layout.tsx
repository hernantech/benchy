import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Benchy — AI Hardware Test Agent",
  description:
    "AI agent that controls real lab instruments to test, diagnose, and fix hardware autonomously.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <nav className="fixed top-0 z-50 w-full border-b border-border bg-background/80 backdrop-blur-md h-14 flex items-center px-6 justify-between">
          <div className="flex items-center gap-3">
            <span className="text-primary font-semibold text-lg font-mono">
              benchy
            </span>
            <span className="text-muted-foreground text-sm">
              AI Hardware Test Agent
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <a
              href="/"
              className="text-foreground hover:text-primary transition-colors"
            >
              Runs
            </a>
            <a
              href="/instruments"
              className="text-muted-foreground hover:text-primary transition-colors"
            >
              Instruments
            </a>
            <a
              href="/agent"
              className="text-muted-foreground hover:text-primary transition-colors"
            >
              Agent
            </a>
          </div>
        </nav>
        <main className="flex-1 pt-14">{children}</main>
      </body>
    </html>
  );
}
