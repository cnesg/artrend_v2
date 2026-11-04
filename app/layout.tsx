import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ARTREND — Art Intelligence Magazine",
  description: "Daily art trend insight: exhibitions, galleries, artists, rookies, criticism and the art press, read by explicit logic.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
