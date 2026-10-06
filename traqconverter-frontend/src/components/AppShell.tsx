"use client"

import { ReactNode, useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api"
import { clearToken } from "@/lib/auth"
import { isOpenRoute, isPublicRoute } from "@/lib/routes"
import CompanyLine from "@/components/legal/CompanyLine"
import NotificationBell from "@/components/NotificationBell"
import { isStaffRole } from "@/lib/staff"
import { loadWallet, planFor, resetWallet, useWallet, type PlanFeature } from "@/lib/plan"
import { findPlan, usePlans } from "@/lib/plans"
import { BrandMark, BrandName } from "@/components/brand/Logo"

type NavItem = {
  name: string
  path: string
  match: string
  icon: ReactNode
  feature?: PlanFeature
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
const IconTemplate = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>
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
const IconCard = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M7 15h4"/></svg>
)
const IconChart = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>
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
      { name: "Translation Memory", path: "/translation-memory", match: "/translation-memory", icon: IconMemory, feature: "terminology_memory" },
      { name: "Glossary", path: "/settings/glossary", match: "/settings/glossary", icon: IconBook, feature: "glossaries" },
      { name: "Templates", path: "/templates", match: "/templates", icon: IconTemplate, feature: "templates" },
      { name: "Certifications", path: "/certifications", match: "/certifications", icon: IconShield, feature: "certifications" },
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

const STAFF_GROUP: NavGroup = {
  label: "ADMIN",
  items: [{ name: "AI usage", path: "/admin/usage", match: "/admin/usage", icon: IconChart }],
}

export default function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname() || "/"

  const [projectCount, setProjectCount] = useState<number | null>(null)
  const wallet = useWallet(false) ?? null
  const catalog = usePlans()
  const credits = wallet ? wallet.total_credits : null
  const [user, setUser] = useState<{
    full_name: string | null
    email: string
    role: string
  } | null>(null)

  const showChrome = !isPublicRoute(pathname) && !isOpenRoute(pathname)
  const [navOpen, setNavOpen] = useState(false)
  const [navPath, setNavPath] = useState(pathname)
  if (navPath !== pathname) {
    setNavPath(pathname)
    setNavOpen(false)
  }

  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNavOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [navOpen])

  useEffect(() => {
    if (!showChrome) return

    const fetchCredits = () => loadWallet(true)

    const fetchUser = async () => {
      try {
        const res = await api.get("/auth/me")
        setUser({
          full_name: res.data?.full_name || null,
          email: res.data?.email || "",
          role: res.data?.role || "",
        })
      } catch {
        setUser(null)
      }
    }

    const fetchProjectCount = async () => {
      try {
        const res = await api.get("/projects/")
        const list = Array.isArray(res.data) ? res.data : []
        setProjectCount(list.length)
      } catch {
        setProjectCount(null)
      }
    }

    const refreshAll = () => {
      fetchCredits()
      fetchUser()
      fetchProjectCount()
    }

    refreshAll()

    const onFocus = () => refreshAll()
    const onSidebarRefresh = () => refreshAll()
    window.addEventListener("focus", onFocus)
    window.addEventListener("sidebar:refresh", onSidebarRefresh)
    return () => {
      window.removeEventListener("focus", onFocus)
      window.removeEventListener("sidebar:refresh", onSidebarRefresh)
    }
  }, [showChrome])

  if (!showChrome) {
    return <>{children}</>
  }

  const handleLogout = async () => {

    try {
      await api.post("/auth/logout")
    } catch {

    }
    clearToken()
    resetWallet()
    router.replace("/login")
  }

  const tier = wallet?.tier || ""
  const paidPlan = findPlan(catalog, tier)
  const planLabel = paidPlan
    ? `${paidPlan.name} plan`
    : tier === "TRIAL"
    ? "Free trial"
    : tier === "EXPIRED"
    ? "Trial ended"
    : tier
    ? `${tier.charAt(0)}${tier.slice(1).toLowerCase()} plan`
    : "—"

  const subscriptionAllowance = paidPlan
    ? paidPlan.credits
    : tier === "TRIAL"
    ? catalog?.trial.credits ?? 0
    : 0

  const subscriptionRemaining = wallet?.subscription_credits ?? 0
  const purchasedRemaining = wallet?.purchased_credits ?? 0
  const remaining = credits ?? subscriptionRemaining + purchasedRemaining

  const subscriptionUsed = Math.max(
    0,
    subscriptionAllowance - subscriptionRemaining,
  )
  const pct =
    subscriptionAllowance === 0
      ? 0
      : Math.min(
          100,
          Math.round((subscriptionUsed / subscriptionAllowance) * 100),
        )

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
    if (subscriptionAllowance === 0 && purchasedRemaining === 0)
      return "No credits yet"
    const sub = `${subscriptionUsed} / ${subscriptionAllowance} subscription used`
    const top =
      purchasedRemaining > 0
        ? ` · +${purchasedRemaining.toLocaleString()} purchased`
        : ""
    return `${sub}${top}`
  })()

  const navGroups = isStaffRole(user?.role) ? [...NAV_GROUPS, STAFF_GROUP] : NAV_GROUPS
  const allMatches = navGroups.flatMap((g) => g.items.map((i) => i.match))
  const activeMatch = (() => {

    if (allMatches.includes(pathname)) return pathname

    const candidates = allMatches
      .filter((m) => m !== "/" && pathname.startsWith(m + "/"))
      .sort((a, b) => b.length - a.length)
    return candidates[0] || ""
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
      {}
      {navOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40"
          style={{ background: "rgba(31, 42, 46, 0.35)" }}
          onClick={() => setNavOpen(false)}
        />
      )}
      <aside
        className={`w-64 shrink-0 flex flex-col justify-between fixed inset-y-0 left-0 z-50 transition-transform lg:static lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{
          background: "#f3ecdb",
          borderRight: "1px solid #e7ddc5",
        }}
      >
        <div className="px-5 py-6 overflow-y-auto">
          {}
          <div className="flex items-center gap-3 mb-10">
            <BrandMark size={40} />
            <div className="leading-tight">
              <div className="font-semibold text-[17px]" style={{ color: "#1f2a2e" }}>
                <BrandName />
              </div>
              <div className="text-[10px] tracking-[0.18em]" style={{ color: "#8a8270" }}>
                WORKSPACE
              </div>
            </div>
          </div>

          {}
          {navGroups.map((group) => (
            <div key={group.label} className="mb-7">
              <div
                className="text-[11px] font-medium mb-2 px-2 tracking-[0.14em]"
                style={{ color: "#9a9178" }}
              >
                {group.label}
              </div>

              <nav className="flex flex-col gap-1">
                {group.items.map((item) => {
                  const active = item.match === activeMatch

                  const locked = !!(item.feature && wallet && !wallet.features[item.feature])
                  const badge =
                    item.name === "Projects"
                      ? projectCount !== null
                        ? String(projectCount)
                        : undefined
                      : undefined

                  return (
                    <Link
                      key={item.path}
                      href={item.path}
                      prefetch
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
                      {locked && item.feature && (
                        <span
                          className="inline-flex items-center gap-1 text-[10px] font-semibold tracking-[0.06em] px-1.5 py-0.5 rounded-full uppercase"
                          style={{
                            background: active ? "#e6f2f0" : "#ede3cc",
                            color: active ? "#0a7870" : "#8a8270",
                          }}
                          title={`Available on ${planFor(item.feature)}`}
                        >
                          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <rect x="4" y="11" width="16" height="10" rx="2" />
                            <path d="M8 11V7a4 4 0 0 1 8 0v4" />
                          </svg>
                          {planFor(item.feature)}
                        </span>
                      )}
                    </Link>
                  )
                })}
              </nav>
            </div>
          ))}
        </div>

        {}
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
                          paidPlan ? "#0a7870" : "#c88a1a"
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
            {subscriptionAllowance > 0 && (
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
          <div className="mt-4 px-1">
            <CompanyLine compact />
          </div>
        </div>
      </aside>

      {}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <header
          className="px-4 sm:px-8 pt-4 sm:pt-6 pb-4 flex items-center justify-between gap-3"
          style={{ background: "#faf5ee" }}
        >
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="lg:hidden w-10 h-10 rounded-full flex items-center justify-center shrink-0"
            style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#4a4638" }}
            aria-label="Open menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
          </button>
          <div className="flex-1" />

          <div className="flex items-center gap-3 sm:gap-4 min-w-0">
            <div
              className="hidden md:flex items-center gap-2 px-4 py-2 rounded-full w-64 xl:w-80"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
            >
              <span style={{ color: "#9a9178" }}>{IconSearch}</span>
              <input
                type="search"
                placeholder="Search projects…"
                aria-label="Search projects"
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return
                  const q = e.currentTarget.value.trim()
                  router.push(q ? `/jobs?q=${encodeURIComponent(q)}` : "/jobs")
                }}
                className="flex-1 bg-transparent outline-none text-sm"
                style={{ color: "#1f2a2e" }}
              />
            </div>

            <NotificationBell />

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
                  className="hidden sm:block text-sm font-medium truncate max-w-[160px]"
                  style={{ color: "#1f2a2e" }}
                >
                  {displayName}
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-4 sm:px-8 pb-10">
          {children}
        </main>
      </div>
    </div>
  )
}
