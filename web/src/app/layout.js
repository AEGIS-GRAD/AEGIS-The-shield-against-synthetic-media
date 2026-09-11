import "./globals.css";

export const metadata = {
  title: "AEGIS — Synthetic Media Verification Workstation",
  description: "Agentic deepfake verification system and multi-modal media analysis workstation",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0b0f17] text-slate-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
