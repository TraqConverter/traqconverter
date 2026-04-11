"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

export default function GlossaryPage() {
  const [terms, setTerms] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const [sourceTerm, setSourceTerm] = useState("")
  const [targetTerm, setTargetTerm] = useState("")

  const [sourceLang, setSourceLang] = useState("English")
  const [targetLang, setTargetLang] = useState("Spanish")

  useEffect(() => {
    fetchTerms()
  }, [])

  const fetchTerms = async () => {
    try {
      const res = await api.get("/glossary")
      setTerms(res.data)
    } catch (err) {
      console.error("GLOSSARY ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  const addTerm = async () => {
    if (!sourceTerm || !targetTerm) return

    try {
      await api.post("/glossary", {
        source_language: sourceLang,
        target_language: targetLang,
        source_term: sourceTerm,
        target_term: targetTerm,
      })

      setSourceTerm("")
      setTargetTerm("")

      fetchTerms()
    } catch (err) {
      console.error("ADD ERROR:", err)
    }
  }

  const deleteTerm = async (id: string) => {
    try {
      await api.delete(`/glossary/${id}`)
      fetchTerms()
    } catch (err) {
      console.error("DELETE ERROR:", err)
    }
  }

  if (loading) return <div className="p-6">Loading glossary...</div>

  return (
    <div className="p-6 space-y-6 max-w-3xl">

      <div>
        <h1 className="text-2xl font-semibold">Glossary</h1>
        <p className="text-sm text-gray-500">
          Manage translation terms for consistency
        </p>
      </div>

      <div className="border p-4 rounded-lg space-y-3 bg-white">

        <div className="flex gap-2">
          <input
            placeholder="Source term"
            value={sourceTerm}
            onChange={(e) => setSourceTerm(e.target.value)}
            className="border p-2 rounded w-full"
          />
          <input
            placeholder="Target term"
            value={targetTerm}
            onChange={(e) => setTargetTerm(e.target.value)}
            className="border p-2 rounded w-full"
          />
        </div>

        <div className="flex gap-2">
          <input
            value={sourceLang}
            onChange={(e) => setSourceLang(e.target.value)}
            className="border p-2 rounded w-full"
          />
          <input
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            className="border p-2 rounded w-full"
          />
        </div>

        <button
          onClick={addTerm}
          className="bg-blue-600 text-white px-4 py-2 rounded"
        >
          Add Term
        </button>
      </div>

      <div className="space-y-2">
        {terms.length === 0 && (
          <p className="text-gray-500">No glossary terms yet</p>
        )}

        {terms.map((t) => (
          <div
            key={t.id}
            className="border p-3 rounded flex justify-between items-center bg-white"
          >
            <div>
              <p className="font-medium">
                {t.source_term} → {t.target_term}
              </p>
              <p className="text-xs text-gray-500">
                {t.source_language} → {t.target_language}
              </p>
            </div>

            <button
              onClick={() => deleteTerm(t.id)}
              className="text-red-500 text-sm"
            >
              Delete
            </button>
          </div>
        ))}
      </div>

    </div>
  )
}