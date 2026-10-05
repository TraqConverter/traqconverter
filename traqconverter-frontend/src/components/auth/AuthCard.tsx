import type { ReactNode } from "react"
import CompanyLine from "@/components/legal/CompanyLine"

// The login page's card layout, for the smaller public auth pages.
export default function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-8 sm:p-6" style={{ background: "#faf5ee", color: "#1f2a2e" }}>
      <div
        className="w-full max-w-md rounded-2xl p-6 sm:p-8"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 1px 2px rgba(30,30,20,0.04)" }}
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-lg" style={{ background: "#0a7870" }}>T</div>
          <div className="leading-tight">
            <div className="font-semibold text-[17px]">TraqConverter</div>
            <div className="text-[10px] tracking-[0.18em]" style={{ color: "#8a8270" }}>WORKSPACE</div>
          </div>
        </div>
        <h1 className="text-[26px] font-semibold tracking-tight mb-1" style={{ color: "#1f2a2e" }}>{title}</h1>
        {subtitle && <p className="text-sm mb-6" style={{ color: "#8a8270" }}>{subtitle}</p>}
        {children}
      </div>
      <div className="w-full max-w-md mt-6 px-1">
        <CompanyLine compact />
      </div>
    </div>
  )
}

export function AuthField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block mb-4">
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>{label}</div>
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl" style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}>
        {children}
      </div>
    </label>
  )
}

export function AuthButton({ loading, label, loadingLabel }: { loading: boolean; label: string; loadingLabel: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full flex items-center justify-center gap-2 py-3 rounded-full text-[15px] font-semibold transition hover:brightness-95"
      style={{ background: loading ? "#9bc9c5" : "#0a7870", color: "#fff", cursor: loading ? "not-allowed" : "pointer" }}
    >
      {loading ? loadingLabel : label}
    </button>
  )
}

export function Notice({ tone, children }: { tone: "error" | "ok"; children: ReactNode }) {
  const style = tone === "error" ? { background: "#f2d4cf", color: "#7a2f24" } : { background: "#d9ece9", color: "#0a4f4a" }
  return (
    <div role={tone === "error" ? "alert" : "status"} className="text-sm rounded-lg px-3 py-2 mb-4" style={style}>
      {children}
    </div>
  )
}

export const inputClass = "flex-1 min-w-0 bg-transparent outline-none text-sm"
