"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { api } from "../../lib/api";
export default function WorkspaceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter(); const pathname = usePathname(); const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    if (!api.getToken()) { router.replace(`/login?next=${encodeURIComponent(pathname)}`); return; }
    api.me().then(() => { if (active) setReady(true); }).catch(() => { api.logout(); router.replace("/login"); });
    return () => { active = false; };
  }, [router, pathname]);
  if (!ready) return <main className="auth-loading"><span className="brand-mark">A</span><p>Checking your workspace…</p></main>;
  return <div className="app-shell"><Sidebar /><main className="main-content">{children}</main></div>;
}
