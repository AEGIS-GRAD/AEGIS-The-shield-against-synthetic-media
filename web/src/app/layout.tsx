import "./globals.css";
import { AppShell } from "@/components/aegis/AppShell";

export const metadata = {
  title: "AEGIS — Synthetic Media Verification Workstation",
  description: "Autonomous Synthetic Media Defense & Forensics Workstation",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased min-h-screen">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
