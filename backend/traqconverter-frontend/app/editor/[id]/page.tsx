"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { api } from "@/lib/api"

export default function EditorPage() {
  const { id } = useParams()
  const [segments, setSegments] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchSegments()
  }, [])

  const fetchSegments = async () => {
    try {
      const res = await api.get(`/projects/${id}/segments`)
      setSegments(res.data)
    } catch (err) {
      console.error("SEGMENTS ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-6">Loading...</div>

  if (segments.length === 0) {
    return <div className="p-6">No segments found</div>
  }

  return (
    <div className="p-6 space-y-4">
      {segments.map((seg) => (
        <div key={seg.id} className="border p-4 rounded">
          <p className="text-sm text-gray-500">Source</p>
          <p>{seg.source_text}</p>

          <p className="text-sm text-gray-500 mt-2">Translation</p>
          <textarea
            defaultValue={seg.translated_text || ""}
            className="w-full border p-2 mt-1"
          />
        </div>
      ))}
    </div>
  )
}