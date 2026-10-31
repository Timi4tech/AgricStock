"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "../../lib/api";
const links = [{ href: "/dashboard", label: "Overview", icon: "▦" }, { href: "/stock", label: "Stock register", icon: "▤" }, { href: "/movements", label: "Stock movements", icon: "⇄" }];
export function Sidebar() {
  const pathname = usePathname(); const router = useRouter();
  function signOut() { api.logout(); router.replace("/login"); }
  return <aside className="sidebar"><Link href="/dashboard" className="brand"><span className="brand-mark">A</span><span><strong>AgroStock</strong><small>Farm inventory</small></span></Link><div className="nav-label">WORKSPACE</div><nav>{links.map(link => <Link key={link.href} href={link.href} className={`nav-link ${(pathname === link.href || pathname.startsWith(link.href + "/")) ? "active" : ""}`}><span className="nav-icon">{link.icon}</span>{link.label}</Link>)}</nav><div className="sidebar-bottom"><div className="help-icon">?</div><div><strong>Field testing mode</strong><p>Built to learn from farmers.</p><button type="button" className="signout-button" onClick={signOut}>Sign out ↗</button></div></div></aside>;
}
