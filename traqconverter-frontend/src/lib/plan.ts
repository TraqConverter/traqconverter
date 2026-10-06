"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

// Mirrors the flags in backend/app/core/plan_features.py.
export type PlanFeature = "terminology_memory" | "glossaries" | "certifications" | "templates" | "team_collaboration"

export type WalletInfo = {
  tier: string
  features: Record<string, boolean>
  trial_days_left: number | null
  plan_type: string
  subscription_credits: number
  purchased_credits: number
  total_credits: number
}

// "allowed" also covers a failed wallet lookup: the page then relies on the API's own 403.
export type Access = "loading" | "allowed" | "locked"

// undefined: not loaded yet; null: the lookup failed.
let current: WalletInfo | null | undefined
let inFlight: Promise<WalletInfo | null> | null = null
const listeners = new Set<(w: WalletInfo | null | undefined) => void>()

function publish(w: WalletInfo | null | undefined) {
  current = w
  listeners.forEach((l) => l(w))
}

export function loadWallet(force = false): Promise<WalletInfo | null> {
  if (inFlight) return inFlight
  if (!force && current !== undefined) return Promise.resolve(current)
  inFlight = api
    .get("/billing/wallet")
    .then((res) => {
      const d = res.data || {}
      return {
        tier: String(d.tier || "").toUpperCase(),
        features: d.features || {},
        trial_days_left: d.trial_days_left ?? null,
        plan_type: d.plan_type || "",
        subscription_credits: d.subscription_credits || 0,
        purchased_credits: d.purchased_credits || 0,
        total_credits: d.total_credits || 0,
      }
    })
    .catch(() => null)
    .then((w) => {
      inFlight = null
      publish(w)
      return w
    })
  return inFlight
}

export function resetWallet() {
  inFlight = null
  publish(undefined)
}

export function accessOf(wallet: WalletInfo | null | undefined, feature: PlanFeature): Access {
  if (wallet === undefined) return "loading"
  if (wallet === null) return "allowed"
  return wallet.features[feature] ? "allowed" : "locked"
}

// autoLoad=false only listens, for places that also render on signed-out pages.
export function useWallet(autoLoad = true): WalletInfo | null | undefined {
  const [wallet, setWallet] = useState<WalletInfo | null | undefined>(current)
  useEffect(() => {
    listeners.add(setWallet)
    if (autoLoad) void loadWallet().then(setWallet)
    return () => {
      listeners.delete(setWallet)
    }
  }, [autoLoad])
  return wallet
}

export function useFeature(feature: PlanFeature): Access {
  return accessOf(useWallet(), feature)
}

// The cheapest plan that includes the feature.
export function planFor(feature: PlanFeature): "Basic" | "Pro" {
  return feature === "templates" || feature === "team_collaboration" ? "Basic" : "Pro"
}
