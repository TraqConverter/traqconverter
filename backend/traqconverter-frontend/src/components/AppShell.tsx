"use client"

import { ReactNode, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { api } from "@/lib/api"
import { getToken, clearToken } from "@/lib/auth"

// ============================================================
// TRAQCONVERTER — ESPRESSO-STYLED APP SHELL
// Warm cream palette + teal accent
// ============================================================

type NavItem = {
  name: string
  path: string
  match: string
  icon: ReactNode
}

type NavGroup = {
  label: string
  items: NavItem[]
}

const IconHome = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>
)
const IconPlus = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/><path d="M4 20h16" opacity="0"/></svg>
)
const IconFolder = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>
)
const IconMemory = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>
)
const IconBook = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22.5Z"/><path d="M4 4.5v18"/></svg>
)
const IconShield = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6Z"/><path d="m9 12 2 2 4-4"/></svg>
)
const IconUsers = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-3.5 3.3-5.5 6.5-5.5s6 2 6.5 5.5"/><circle cx="17" cy="9" r="2.8"/><path d="M15.5 14.5c2.6 0 5 1.6 5.5 4"/></svg>
)
const IconSettings = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>
)
const IconBell = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>
)
const IconCard = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M7 15h4"/></svg>
)
const IconSearch = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
)

const NAV_GROUPS: NavGroup[] = [
  {
    label: "WORKSPACE",
    items: [
      { name: "Dashboard", path: "/dashboard", match: "/dashboard", icon: IconHome },
      { name: "New project", path: "/new-translation", match: "/new-translation", icon: IconPlus },
      { name: "Projects", path: "/jobs", match: "/jobs", icon: IconFolder },
    ],
  },
  {
    label: "ASSETS",
    items: [
      { name: "Translation Memory", path: "/translation-memory", match: "/translation-memory", icon: IconMemory },
      { name: "Glossary", path: "/settings/glossary", match: "/settings/glossary", icon: IconBook },
      { name: "Certifications", path: "/certifications", match: "/certifications", icon: IconShield },
    ],
  },
  {
    label: "ACCOUNT",
    items: [
      { name: "Billing", path: "/billing", match: "/billing", icon: IconCard },
      { name: "Members", path: "/settings", match: "/settings", icon: IconUsers },
      { name: "Settings", path: "/settings/account", match: "/settings/account", icon: IconSettings },
    ],
  },
]

export default function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()

  const [loading, setLoading] = useState(true)
  const [credits, setCredits] = useState<number | null>(null)
  const [wallet, setWallet] = useState<{
    tier: string
    trial_days_left: number | null
    plan_type: string
    subscription_credits: number
    purchased_credits: number
  } | null>(null)
  const [user, setUser] = useState<{
    full_name: string | null
    email: string
  } | null>(null)

  useEffect(() => {
    const token = getToken()

    const isAuthPage =
      pathname === "/login" ||
      pathname === "/register" ||
      pathname.startsWith("/auth")

    if (!token && !isAuthPage) {
      router.replace("/login")
    } else if (token && isAuthPage) {
      router.replace("/dashboard")
    } else {
      setLoading(false)
    }
  }, [pathname, router])

  useEffect(() => {
    // Don't call protected endpoints on auth pages or before login
    const token = getToken()
    const isAuthPage =
      pathname === "/login" ||
      pathname === "/register" ||
      pathname.startsWith("/auth")

    if (!token || isAuthPage) {
      setCredits(0)
      setWallet(null)
      setUser(null)
      return
    }

    const fetchCredits = async () => {
      try {
        const res = await api.get("/billing/wallet")
        setCredits(res.data.total_credits)
        setWallet({
          tier: (res.data.tier || "").toUpperCase(),
          trial_days_left: res.data.trial_days_left ?? null,
          plan_type: res.data.plan_type || "",
          subscription_credits: res.data.subscription_credits || 0,
          purchased_credits: res.data.purchased_credits || 0,
        })
      } catch {
        // Silently fall back — auth-related errors are handled by the interceptor
        setCredits(0)
        setWallet(null)
      }
    }

    const fetchUser = async () => {
      try {
        const res = await api.get("/auth/me")
        setUser({
          full_name: res.data?.full_name || null,
          email: res.data?.email || "",
        })
      } catch {
        setUser(null)
      }
    }

    fetchCredits()
    fetchUser()
  }, [pathname])

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: "#faf5ee" }}>
        <div style={{ color: "#6b6558" }}>Loading...</div>
      </div>
    )
  }

  const isAuthPage =
    pathname === "/login" ||
    pathname === "/register" ||
    pathname.startsWith("/auth")

  if (isAuthPage) {
    return <>{children}</>
  }

  const handleLogout = () => {
    clearToken()
    router.replace("/login")
  }

  // Sidebar usage card is driven by the real wallet tier returned by
  // /billing/wallet. Pro = 29 credits, Basic = 19, Trial = 1, plus any
  // top-ups the user has purchased.
  const tier = wallet?.tier || ""
  const planLabel =
    tier === "PRO"
      ? "Pro plan"
      : tier === "BASIC"
      ? "Basic plan"
      : tier === "TRIAL"
      ? "Free trial"
      : tier === "EXPIRED"
      ? "Trial ended"
      : "—"

  const subscriptionAllowance =
    tier === "PRO" ? 29 : tier === "BASIC" ? 19 : tier === "TRIAL" ? 1 : 0
  const purchased = wallet?.purchased_credits || 0
  const remaining = credits ?? 0
  const creditsTotal = subscriptionAllowance + purchased
  const creditsUsed = Math.max(0, creditsTotal - remaining)
  const pct =
    credits === null || creditsTotal === 0
      ? 0
      : Math.min(100, Math.round((creditsUsed / creditsTotal) * 100))

  const planSubtitle = (() => {
    if (tier === "TRIAL") {
      const d = wallet?.trial_days_left
      if (d != null && d > 0)
        return `${d} day${d === 1 ? "" : "s"} left · ${remaining} credit${
          remaining === 1 ? "" : "s"
        }`
      return "Trial ending today"
    }
    if (tier === "EXPIRED") return "Subscribe to continue"
    if (creditsTotal === 0) return "No credits yet"
    return `${creditsUsed.toLocaleString()} / ${creditsTotal.toLocaleString()} credits used`
  })()

  const displayName = user?.full_name?.trim() || user?.email?.split("@")[0] || ""
  const initials = (() => {
    const name = user?.full_name?.trim()
    if (name) {
      const parts = name.split(/\s+/).filter(Boolean)
      if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
      return parts[0].slice(0, 2).toUpperCase()
    }
    if (user?.email) return user.email.slice(0, 2).toUpperCase()
    return "—"
  })()

  return (
    <div className="flex h-screen" style={{ background: "#faf5ee", color: "#1f2a2e" }}>
      {/* ==================== SIDEBAR ==================== */}
      <aside
        className="w-64 flex flex-col justify-between"
        style={{
          background: "#f3ecdb",
          borderRight: "1px solid #e7ddc5",
        }}
      >
        <div className="px-5 py-6 overflow-y-auto">
          {/* LOGO */}
          <div className="flex items-center gap-3 mb-10">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center font-bold text-white text-lg"
              style={{ background: "#0a7870" }}
            >
              T
            </div>
            <div className="leading-tight">
              <div className="font-semibold text-[17px]" style={{ color: "#1f2a2e" }}>
                TraqConverter
              </div>
              <div className="text-[10px] tracking-[0.18em]" style={{ color: "#8a8270" }}>
                WORKSPACE
              </div>
            </div>
          </div>

          {/* NAV GROUPS */}
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-7">
              <div
                className="text-[11px] font-medium mb-2 px-2 tracking-[0.14em]"
                style={{ color: "#9a9178" }}
              >
                {group.label}
              </div>

              <nav className="flex flex-col gap-1">
                {group.items.map((item) => {
                  const active =
                    pathname === item.match ||
                    (item.match !== "/" && pathname.startsWith(item.match.split("?")[0] + "/")) ||
                    pathname === item.match.split("?")[0]

                  const badge =
                    item.name === "Projects" ? "12" : undefined

                  return (
                    <button
                      key={item.path}
                      onClick={() => router.push(item.path)}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition text-sm text-left"
                      style={{
                        background: active ? "#ffffff" : "transparent",
                        color: active ? "#0a7870" : "#4a4638",
                        fontWeight: active ? 600 : 500,
                        boxShadow: active ? "0 1px 2px rgba(30,30,20,0.04)" : "none",
                      }}
                      onMouseEnter={(e) => {
                        if (!active) (e.currentTarget.style.background = "#ede3cc")
                      }}
                      onMouseLeave={(e) => {
                        if (!active) (e.currentTarget.style.background = "transparent")
                      }}
                    >
                      <span
                        style={{ color: active ? "#0a7870" : "#6b6558" }}
                      >
                        {item.icon}
                      </span>
                      <span className="flex-1">{item.name}</span>
                      {badge && (
                        <span
                          className="text-[11px] px-2 py-0.5 rounded-full"
                          style={{
                            background: active ? "#e6f2f0" : "#ede3cc",
                            color: active ? "#0a7870" : "#6b6558",
                          }}
                        >
                          {badge}
                        </span>
                      )}
                    </button>
                  )
                })}
              </nav>
            </div>
          ))}
        </div>

        {/* PLAN CARD — dynamic from wallet.tier */}
        <div className="px-5 pb-5">
          <div
            className="rounded-xl p-4"
            style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
          >
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-4 h-4 rounded-full"
                style={{
                  background:
                    tier === "EXPIRED"
                      ? "#cfc6ad"
                      : `conic-gradient(${
                          tier === "PRO"
                            ? "#0a7870"
                            : tier === "BASIC"
                            ? "#0a7870"
                            : "#c88a1a"
                        } 0 ${100 - pct}%, #e7ddc5 0 100%)`,
                }}
              />
              <span
                className="font-semibold text-sm"
                style={{ color: "#1f2a2e" }}
              >
                {planLabel}
              </span>
            </div>
            <div className="text-xs mb-2" style={{ color: "#6b6558" }}>
              {planSubtitle}
            </div>
            {creditsTotal > 0 && (
              <div
                className="h-1.5 rounded-full overflow-hidden"
                style={{ background: "#f3ecdb" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${pct}%`,
                    background:
                      tier === "TRIAL" ? "#c88a1a" : "#d98b5f",
                  }}
                />
              </div>
            )}
            {(tier === "TRIAL" || tier === "EXPIRED") && (
              <button
                onClick={() => router.push("/billing")}
                className="mt-3 w-full text-[12px] font-semibold py-1.5 rounded-full transition"
                style={{ background: "#0a7870", color: "#fff" }}
              >
                Upgrade to Pro
              </button>
            )}
            <button
              onClick={handleLogout}
              className="mt-3 text-[11px] hover:underline"
              style={{ color: "#8a8270" }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* ==================== MAIN ==================== */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header
          className="px-8 pt-6 pb-4 flex items-center justify-between"
          style={{ background: "#faf5ee" }}
        >
          <div className="flex-1" />

          <div className="flex items-center gap-4">
            <div
              className="flex items-center gap-2 px-4 py-2 rounded-full w-80"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
            >
              <span style={{ color: "#9a9178" }}>{IconSearch}</span>
              <input
                placeholder="Search projects, segments..."
                className="flex-1 bg-transparent outline-none text-sm"
                style={{ color: "#1f2a2e" }}
              />
            </div>

            <button
              className="w-10 h-10 rounded-full flex items-center justify-center transition"
              style={{
                background: "#ffffff",
                border: "1px solid #e7ddc5",
                color: "#6b6558",
              }}
              aria-label="Notifications"
            >
              {IconBell}
            </button>

            <div className="flex items-center gap-2">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-semibold"
                style={{ background: "#cfe6e2", color: "#0a7870" }}
                title={user?.email || ""}
              >
                {initials}
              </div>
              {displayName && (
                <div
                  className="text-sm font-medium"
                  style={{ color: "#1f2a2e" }}
                >
                  {displayName}
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-8 pb-10">
          {children}
        </main>
      </div>
    </div>
  )
}
