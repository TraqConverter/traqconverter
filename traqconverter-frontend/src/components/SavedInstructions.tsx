"use client"

import { useCallback, useEffect, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import { useFeature } from "@/lib/plan"

export const MAX_NAME = 80

export type SavedInstruction = {
  id: string
  name: string
  text: string
}

// Same plans as templates; Trial gets only the plain textarea.
export function useSavedInstructions() {
  const access = useFeature("templates")
  const enabled = access === "allowed"
  const [items, setItems] = useState<SavedInstruction[]>([])
  const [loaded, setLoaded] = useState(false)

  const reload = useCallback(async () => {
    try {
      const res = await api.get("/instructions")
      setItems(res.data?.items || [])
    } catch {
      setItems([])
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    if (enabled) void reload()
  }, [enabled, reload])

  const create = async (name: string, text: string) => {
    const res = await api.post("/instructions", { name, text })
    const item = res.data as SavedInstruction
    setItems((list) => [...list, item].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })))
    return item
  }

  return { enabled, loaded, items, setItems, reload, create }
}

function IconChevronSmall() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export function SavedInstructionPicker({
  items,
  onPick,
  disabled,
  id = "saved-instructions",
}: {
  items: SavedInstruction[]
  onPick: (text: string) => void
  disabled?: boolean
  id?: string
}) {
  if (!items.length) return null
  return (
    <div className="relative min-w-0">
      <label htmlFor={id} className="sr-only">
        Use saved instructions
      </label>
      <select
        id={id}
        value=""
        disabled={disabled}
        onChange={(e) => {
          const picked = items.find((i) => i.id === e.target.value)
          if (picked) onPick(picked.text)
        }}
        className="w-full min-w-0 appearance-none text-[12px] outline-none rounded-lg pl-3 pr-8 py-1.5 truncate"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e", cursor: disabled ? "not-allowed" : "pointer" }}
      >
        <option value="">Use saved…</option>
        {items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
        <IconChevronSmall />
      </span>
    </div>
  )
}

export function SaveForLater({
  text,
  onSave,
}: {
  text: string
  onSave: (name: string, text: string) => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState("")
  const empty = !text.trim()

  const close = () => {
    setOpen(false)
    setName("")
    setError("")
  }

  const submit = async () => {
    const clean = name.trim()
    if (!clean || busy) return
    setBusy(true)
    setError("")
    try {
      await onSave(clean, text.trim())
      setSaved(clean)
      close()
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't save the instructions."))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div className="flex items-center gap-2 min-w-0">
        <button
          type="button"
          onClick={() => {
            setSaved("")
            setOpen(true)
          }}
          disabled={empty}
          title={empty ? "Write some instructions first" : "Save these instructions for other projects"}
          className="text-[12px] font-semibold hover:underline disabled:no-underline"
          style={{ color: empty ? "#b5ab93" : "#0a7870", cursor: empty ? "not-allowed" : "pointer" }}
        >
          Save for later
        </button>
        {saved && (
          <span className="text-[12px] truncate" style={{ color: "#2d5a24" }}>
            Saved as “{saved}”
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2 min-w-0">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              void submit()
            }
            if (e.key === "Escape") close()
          }}
          maxLength={MAX_NAME}
          placeholder="Name, e.g. Client Rossi – style"
          aria-label="Name for these instructions"
          className="flex-1 min-w-0 text-[12px] outline-none rounded-lg px-3 py-1.5"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!name.trim() || busy}
          className="text-[12px] font-semibold px-3 py-1.5 rounded-full shrink-0"
          style={{
            background: !name.trim() || busy ? "#9bc9c5" : "#0a7870",
            color: "#ffffff",
            cursor: !name.trim() || busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={close}
          className="text-[12px] font-semibold shrink-0"
          style={{ color: "#6b6558" }}
        >
          Cancel
        </button>
      </div>
      {error && (
        <div className="text-[12px] mt-1" style={{ color: "#b14a3a" }}>
          {error}
        </div>
      )}
    </div>
  )
}
