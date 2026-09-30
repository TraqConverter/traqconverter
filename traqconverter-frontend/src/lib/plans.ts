"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

// Prices, pages and seats come from GET /billing/plans (backend/app/core/plan_features.py); never hardcode them here.
export type PlanFeatures = Record<string, boolean>

export type Plan = {
  code: string
  name: string
  price_eur: number
  credits: number
  seats: number
  priority: boolean
  blurb: string
  price_per_page_eur: number
  features: PlanFeatures
  available: boolean
}

export type TrialPlan = {
  code: "TRIAL"
  name: string
  price_eur: number
  credits: number
  days: number
  seats: number
  features: PlanFeatures
}

export type CreditPack = { credits: number; price_eur: number; name: string; note: string; available: boolean }

export type PlanCatalog = {
  currency: string
  contact_email: string
  trial: TrialPlan
  plans: Plan[]
  credit_packs: CreditPack[]
}

// undefined: loading; null: the lookup failed.
let cached: PlanCatalog | null | undefined
let inFlight: Promise<PlanCatalog | null> | null = null

export function loadPlans(): Promise<PlanCatalog | null> {
  if (cached !== undefined) return Promise.resolve(cached)
  if (!inFlight) {
    inFlight = api
      .get("/billing/plans")
      .then((res) => res.data as PlanCatalog)
      .catch(() => null)
      .then((c) => {
        cached = c
        inFlight = null
        return c
      })
  }
  return inFlight
}

export function usePlans(): PlanCatalog | null | undefined {
  const [catalog, setCatalog] = useState<PlanCatalog | null | undefined>(cached)
  useEffect(() => {
    let live = true
    void loadPlans().then((c) => live && setCatalog(c))
    return () => {
      live = false
    }
  }, [])
  return catalog
}

export function findPlan(catalog: PlanCatalog | null | undefined, code: string): Plan | undefined {
  return catalog?.plans.find((p) => p.code === code.toUpperCase())
}

// Any tier the wallet reports that isn't the trial or a lapsed plan is a paid subscription.
export function isPaidTier(tier: string | null | undefined): boolean {
  const t = (tier || "").toUpperCase()
  return t !== "" && !["TRIAL", "EXPIRED", "CREDITS"].includes(t)
}

export function planDisplayName(tier: string | null | undefined): string {
  const t = (tier || "").toLowerCase()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

export function euro(n: number): string {
  return `€${Number.isInteger(n) ? n : n.toFixed(2)}`
}

export function pagesLabel(n: number): string {
  return `${n} page${n === 1 ? "" : "s"}`
}

export function contactHref(catalog: PlanCatalog, plan: Plan): string {
  return `mailto:${catalog.contact_email}?subject=${encodeURIComponent(`TraqConverter ${plan.name} plan`)}`
}

// The bullets a plan card shows: its allowance, then what it adds over the plan below it.
export function planBullets(catalog: PlanCatalog, plan: Plan): string[] {
  const idx = catalog.plans.findIndex((p) => p.code === plan.code)
  const below = idx > 0 ? catalog.plans[idx - 1] : undefined
  const out = [
    `${plan.credits} pages a month (${euro(plan.price_per_page_eur)} a page)`,
    `Up to ${plan.seats} team members`,
  ]
  if (below) out.push(`Everything in ${below.name}`)
  const f = plan.features
  if (!below) {
    if (f.download_translation) out.push("Download finished translations (DOCX & PDF)")
    if (f.templates) out.push("Templates from your delivered documents")
  }
  if (f.terminology_memory && !below?.features.terminology_memory) out.push("Translation memory across projects")
  if (f.glossaries && !below?.features.glossaries) out.push("Glossary enforcement")
  if (f.certifications && !below?.features.certifications)
    out.push("Your certification page & certifications library")
  if (plan.priority) out.push("Priority processing: your documents go first in the queue")
  return out
}
