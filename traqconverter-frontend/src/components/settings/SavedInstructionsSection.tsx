"use client"

import { useState } from "react"
import Link from "next/link"
import { api, apiErrorDetail } from "@/lib/api"
import { useFeature } from "@/lib/plan"
import { MAX_NAME, useSavedInstructions, type SavedInstruction } from "@/components/SavedInstructions"

const MAX_TEXT = 1000

const INPUT_STYLE = { background: "#faf5ee", border: "1px solid #e7ddc5", color: "#1f2a2e" }

function Header() {
  return (
    <div className="mb-5">
      <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
        SAVED INSTRUCTIONS
      </div>
      <h2 className="text-[18px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
        Instructions for the AI
      </h2>
      <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
        Reusable instructions your team can pick on a new project or when regenerating, e.g. one client&apos;s style.
      </p>
    </div>
  )
}

function Editor({
  initial,
  busy,
  error,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: { name: string; text: string }
  busy: boolean
  error: string
  submitLabel: string
  onSubmit: (name: string, text: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial.name)
  const [text, setText] = useState(initial.text)
  const ready = !!name.trim() && !!text.trim() && !busy
  return (
    <div className="space-y-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={MAX_NAME}
        placeholder="Name, e.g. UK immigration (UKVI)"
        aria-label="Name"
        className="w-full min-w-0 text-sm outline-none rounded-xl px-3 py-2"
        style={INPUT_STYLE}
      />
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={MAX_TEXT}
        rows={3}
        placeholder="e.g. Use British spelling. Dates as 12 March 2024."
        aria-label="Instructions"
        className="w-full min-w-0 block text-sm outline-none rounded-xl px-3 py-2 resize-y"
        style={INPUT_STYLE}
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] tabular-nums mr-auto" style={{ color: text.length >= MAX_TEXT ? "#b14a3a" : "#9a9178" }}>
          {text.length}/{MAX_TEXT}
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="text-[13px] font-semibold px-3 py-1.5 rounded-full"
          style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onSubmit(name.trim(), text.trim())}
          disabled={!ready}
          className="text-[13px] font-semibold px-4 py-1.5 rounded-full"
          style={{ background: ready ? "#0a7870" : "#9bc9c5", color: "#ffffff", cursor: ready ? "pointer" : "not-allowed" }}
        >
          {busy ? "Saving…" : submitLabel}
        </button>
      </div>
      {error && (
        <div className="text-[12px]" style={{ color: "#b14a3a" }}>
          {error}
        </div>
      )}
    </div>
  )
}

export default function SavedInstructionsSection() {
  const access = useFeature("templates")
  const { items, setItems, loaded, create } = useSavedInstructions()
  // "new", an item id being edited, or null.
  const [editing, setEditing] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const sort = (list: SavedInstruction[]) =>
    [...list].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }))

  const run = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true)
    setError("")
    try {
      await work()
      setEditing(null)
      setConfirmDelete(null)
    } catch (err) {
      setError(apiErrorDetail(err, fallback))
    } finally {
      setBusy(false)
    }
  }

  const add = (name: string, text: string) =>
    run(async () => {
      await create(name, text)
    }, "Couldn't save the instructions.")

  const update = (id: string, name: string, text: string) =>
    run(async () => {
      const res = await api.patch(`/instructions/${id}`, { name, text })
      setItems((list) => sort(list.map((i) => (i.id === id ? (res.data as SavedInstruction) : i))))
    }, "Couldn't save the changes.")

  const remove = (id: string) =>
    run(async () => {
      await api.delete(`/instructions/${id}`)
      setItems((list) => list.filter((i) => i.id !== id))
    }, "Couldn't delete the instructions.")

  const startEditing = (id: string) => {
    setError("")
    setConfirmDelete(null)
    setEditing(id)
  }

  return (
    <section className="rounded-2xl p-6" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
      <Header />

      {access === "locked" ? (
        <div className="text-sm rounded-xl px-4 py-3" style={{ background: "#faf5ee", color: "#4a4638" }}>
          Saved instructions come with Basic and Pro.{" "}
          <Link href="/billing" className="font-semibold underline" style={{ color: "#0a7870" }}>
            See plans
          </Link>
        </div>
      ) : (
        <>
          {loaded && !items.length && editing !== "new" && (
            <div className="text-sm mb-4" style={{ color: "#8a8270" }}>
              Nothing saved yet. Add one here, or use Save for later under the instructions box on a new project.
            </div>
          )}

          <div>
            {items.map((item, idx) => (
              <div key={item.id} className="py-3" style={{ borderTop: idx ? "1px solid #f1e8d1" : "none" }}>
                {editing === item.id ? (
                  <Editor
                    initial={item}
                    busy={busy}
                    error={error}
                    submitLabel="Save changes"
                    onSubmit={(name, text) => void update(item.id, name, text)}
                    onCancel={() => setEditing(null)}
                  />
                ) : (
                  <>
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold truncate" style={{ color: "#1f2a2e" }}>
                          {item.name}
                        </div>
                        <div className="text-[13px] mt-0.5 line-clamp-2 break-words" style={{ color: "#6b6558" }}>
                          {item.text}
                        </div>
                      </div>
                      {confirmDelete !== item.id && (
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            type="button"
                            onClick={() => startEditing(item.id)}
                            className="text-[12px] font-semibold px-2.5 py-1 rounded-full hover:bg-[#f3ecdb]"
                            style={{ color: "#0a7870" }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setEditing(null)
                              setError("")
                              setConfirmDelete(item.id)
                            }}
                            className="text-[12px] font-semibold px-2.5 py-1 rounded-full hover:bg-[#f9efe9]"
                            style={{ color: "#b14a3a" }}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                    {confirmDelete === item.id && (
                      <div
                        className="flex flex-wrap items-center gap-2 mt-2 rounded-xl px-3 py-2"
                        style={{ background: "#fbeeee", border: "1px solid #f0cccc" }}
                      >
                        <span className="text-[12px] mr-auto" style={{ color: "#7a1f1f" }}>
                          Delete “{item.name}” for everyone on the team?
                        </span>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          className="text-[12px] font-semibold px-2.5 py-1 rounded-full"
                          style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
                        >
                          Keep
                        </button>
                        <button
                          type="button"
                          onClick={() => void remove(item.id)}
                          disabled={busy}
                          className="text-[12px] font-semibold px-2.5 py-1 rounded-full"
                          style={{ background: "#b14a3a", color: "#ffffff" }}
                        >
                          {busy ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>

          {error && editing === null && (
            <div className="text-[12px] mt-2" style={{ color: "#b14a3a" }}>
              {error}
            </div>
          )}

          <div className="mt-3 pt-4" style={{ borderTop: items.length ? "1px solid #f1e8d1" : "none" }}>
            {editing === "new" ? (
              <Editor
                initial={{ name: "", text: "" }}
                busy={busy}
                error={error}
                submitLabel="Save"
                onSubmit={(name, text) => void add(name, text)}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <button
                type="button"
                onClick={() => startEditing("new")}
                className="text-sm font-semibold px-4 py-2 rounded-full"
                style={{ background: "#0a7870", color: "#ffffff" }}
              >
                Add instructions
              </button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
