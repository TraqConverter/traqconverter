"use client"

import { money, type ProjectPayment } from "@/lib/payment"

// The confirmation before a lead releases a protected link by hand. Used on Projects and in the editor.
export default function MarkPaidDialog({
  payment,
  fileName,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  payment: ProjectPayment
  fileName: string
  busy: boolean
  error: string | null
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      onClick={busy ? undefined : onCancel}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(31, 42, 46, 0.45)",
        backdropFilter: "blur(2px)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Mark as paid"
        className="rounded-2xl p-6 w-full max-w-md"
        style={{
          background: "#ffffff",
          border: "1px solid #e7ddc5",
          boxShadow: "0 24px 60px rgba(30,30,20,0.18)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
          MARK AS PAID
        </div>
        <h3 className="text-[18px] font-semibold tracking-tight mb-3 break-words" style={{ color: "#1f2a2e" }}>
          Has {money(payment.amount, payment.currency) || "the payment"} for {fileName || "this document"} arrived?
        </h3>
        <p className="text-sm mb-2" style={{ color: "#6b6558" }}>
          {payment.state === "claimed"
            ? "Your client says they've paid. Check your PayPal or bank account first."
            : "Your client hasn't said they've paid yet. Check your PayPal or bank account first."}
        </p>
        <p className="text-sm mb-5" style={{ color: "#6b6558" }}>
          Marking it as paid releases the document: your client can download the clean file straight away from the
          link you sent.{payment.client_will_be_emailed && " We'll also email your client that it's ready."}{" "}
          This can&apos;t be undone.
        </p>
        {error && (
          <div className="text-sm rounded-lg px-3 py-2 mb-4" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
            {error}
          </div>
        )}
        <div className="flex items-center justify-end gap-2 flex-wrap">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{
              background: busy ? "#9bc9c5" : "#0a7870",
              color: "#fff",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            {busy ? "Marking as paid…" : "Yes, mark as paid and release"}
          </button>
        </div>
      </div>
    </div>
  )
}
