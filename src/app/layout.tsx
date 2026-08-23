import type { Metadata } from "next";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "DataOS",
  description: "Universal Data Operating System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div id="root">{children}</div>
      </body>
    </html>
  );
}
