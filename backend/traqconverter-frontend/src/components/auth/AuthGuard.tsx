"use client"

import { ReactNode } from "react"

// ============================================================
// AuthGuard is now a thin pass-through.
//
// AppShell already runs the canonical auth gate (token → redirect
// /login, no-token-on-private-page → redirect /login,
// token-on-auth-page → /dashboard). Having two components race the
// same logic produced the /login ↔ /dashboard bounce loop the audit
// flagged as HIGH-10. We keep this file so existing imports still
// work, but it doesn't redirect any more — every routing decision
// goes through AppShell.
// ============================================================

export default function AuthGuard({ children }: { children: ReactNode }) {
  return <>{children}</>
}
