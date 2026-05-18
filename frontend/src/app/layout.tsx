import type { Metadata } from "next";
import "./globals.css";
import { ReduxProvider } from "./providers";

export const metadata: Metadata = {
  title: "deez-forex-ai",
  description: "Intelligent 24/7 Forex Trading Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <ReduxProvider>{children}</ReduxProvider>
      </body>
    </html>
  );
}
