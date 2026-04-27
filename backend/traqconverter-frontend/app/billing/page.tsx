"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

export default function BillingPage() {
  const [wallet, setWallet] = useState<any>(null)
  const [transactions, setTransactions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [purchasing, setPurchasing] = useState(false)

  useEffect(() => {
    fetchBilling()
  }, [])

  const fetchBilling = async () => {
    try {
      const [walletRes, txRes] = await Promise.all([
        api.get("/billing/wallet"),
        api.get("/billing/transactions")
      ])

      setWallet(walletRes.data)
      setTransactions(txRes.data || [])

    } catch (err) {
      console.error("BILLING ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  // ============================================================
  // 🔥 PURCHASE CREDITS (FIX)
  // ============================================================
  const handlePurchaseCredits = async () => {
    try {
      setPurchasing(true)

      // 👉 you can later replace 100 with input from user
      const amount = 100

      const res = await api.post("/subscription/purchase-credits", null, {
        params: { amount }
      })

      if (res.data?.checkout_url) {
        window.location.href = res.data.checkout_url
      }

    } catch (err) {
      console.error("PURCHASE ERROR:", err)
      alert("Failed to start purchase")
    } finally {
      setPurchasing(false)
    }
  }

  if (loading) {
    return <div className="p-6">Loading billing...</div>
  }

  if (!wallet) {
    return <div className="p-6 text-red-500">Failed to load billing</div>
  }

  const totalCredits = wallet.total_credits || 0

  return (
    <div className="space-y-6">

      {/* HEADER */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-semibold">Billing & Credits</h1>
          <p className="text-gray-500 text-sm">
            Manage your subscription and usage
          </p>
        </div>

        <button
          onClick={handlePurchaseCredits}
          disabled={purchasing}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg disabled:opacity-50"
        >
          {purchasing ? "Redirecting..." : "Purchase Credits"}
        </button>
      </div>

      {/* CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">

        <div className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-6 rounded-xl">
          <p className="text-sm opacity-80">Total Credits</p>
          <h2 className="text-3xl font-bold mt-2">{totalCredits}</h2>
        </div>

        <div className="bg-white p-6 rounded-xl shadow">
          <p className="text-sm text-gray-500">Subscription Credits</p>
          <h2 className="text-3xl font-bold mt-2">
            {wallet.subscription_credits}
          </h2>
        </div>

        <div className="bg-white p-6 rounded-xl shadow">
          <p className="text-sm text-gray-500">Purchased Credits</p>
          <h2 className="text-3xl font-bold mt-2">
            {wallet.purchased_credits}
          </h2>
        </div>

        <div className="bg-white p-6 rounded-xl shadow">
          <p className="text-sm text-gray-500">Plan</p>
          <h2 className="text-xl font-bold mt-2">
            {wallet.plan_type}
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            {wallet.subscription_status}
          </p>
        </div>

      </div>

      {/* TRANSACTIONS */}
      <div className="bg-white rounded-xl shadow overflow-hidden">

        <div className="p-4 border-b font-semibold">
          Recent Transactions
        </div>

        <table className="w-full text-sm">

          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="p-4">Type</th>
              <th>Amount</th>
              <th>Reference</th>
              <th>Date</th>
            </tr>
          </thead>

          <tbody>

            {transactions.length === 0 && (
              <tr>
                <td colSpan={4} className="p-6 text-center text-gray-500">
                  No transactions yet
                </td>
              </tr>
            )}

            {transactions.map((t) => (
              <tr key={t.id} className="border-t">

                <td className="p-4 capitalize">
                  {t.type}
                </td>

                <td className={`font-medium ${
                  t.amount > 0 ? "text-green-600" : "text-red-600"
                }`}>
                  {t.amount > 0 ? "+" : ""}{t.amount}
                </td>

                <td>
                  {t.reference_id || "-"}
                </td>

                <td>
                  {new Date(t.created_at).toLocaleDateString()}
                </td>

              </tr>
            ))}

          </tbody>

        </table>

      </div>

    </div>
  )
}