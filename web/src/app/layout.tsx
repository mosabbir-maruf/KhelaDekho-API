import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Sidebar from "../components/Sidebar";
import Navbar from "../components/Navbar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "KhelaDekho - Premium Sports Streaming",
  description: "Aggregating and decrypting live feeds natively at the edge with Apple-inspired cinematic interface.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-[#09090B] text-[#FAFAFA]">
        <Sidebar />
        <div className="flex flex-col flex-1 min-h-screen">
          <Navbar />
          <main className="flex-1 px-6 py-8 md:pl-72 max-w-[1600px] w-full mx-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
