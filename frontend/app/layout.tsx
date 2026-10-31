import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = { title: "AgroStock | Farm inventory", description: "Simple stock records for agribusinesses" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
