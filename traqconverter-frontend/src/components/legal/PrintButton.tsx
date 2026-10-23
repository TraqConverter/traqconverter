"use client"

export default function PrintButton({ label = "Save as PDF" }: { label?: string }) {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      style={{
        fontSize: 14,
        fontWeight: 600,
        color: "#ffffff",
        background: "#0a7870",
        padding: "10px 20px",
        borderRadius: 999,
        border: "none",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  )
}
