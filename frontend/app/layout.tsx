import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Yo-kai Mail",
  description: "Turn a website into a campaign-ready email.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
