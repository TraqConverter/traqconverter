"use client"

import Link from "next/link"

import { TableScroll } from "@/components/legal/LegalPage"
import { euro, usePlans } from "@/lib/plans"

// Live from GET /billing/plans so the Terms never drift from what checkout charges.
export default function PlanTable() {
  const catalog = usePlans()
  if (!catalog) {
    return (
      <p>
        The current plans and credit packs are listed under <Link href="/#pricing">Pricing</Link>.
      </p>
    )
  }
  return (
    <>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Plan</th>
              <th>Price per month (excl. VAT)</th>
              <th>Credits per month</th>
              <th>Team size</th>
            </tr>
          </thead>
          <tbody>
            {catalog.plans.map((p) => (
              <tr key={p.code}>
                <td>{p.name}</td>
                <td>{euro(p.price_eur)}</td>
                <td>{p.credits}</td>
                <td>{p.seats}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Credit pack</th>
              <th>Price (excl. VAT)</th>
            </tr>
          </thead>
          <tbody>
            {catalog.credit_packs.map((c) => (
              <tr key={c.credits}>
                <td>{c.credits} credits</td>
                <td>{euro(c.price_eur)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </>
  )
}
