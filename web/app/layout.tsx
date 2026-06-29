import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Provenance",
  description: "Provenance-aware RAG + Knowledge Graph",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="nav">
          <Link href="/" className="brand">Provenance</Link>
          <nav>
            <Link href="/ingest">Ingest</Link>
            <Link href="/chat">Chat</Link>
          </nav>
        </header>
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
