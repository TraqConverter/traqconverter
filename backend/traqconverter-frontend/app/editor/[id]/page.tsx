"use client"

import { useEffect, useState, useRef } from "react"
import { useParams } from "next/navigation"
import { api } from "@/lib/api"
import debounce from "lodash/debounce"

export default function EditorPage() {
  const params = useParams()
  const id = params?.id as string

  const [segments, setSegments] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null)
  const [savingMap, setSavingMap] = useState<Record<string, string>>({})

  const [comments, setComments] = useState<any[]>([])
  const [newComment, setNewComment] = useState("")
  const [loadingComments, setLoadingComments] = useState(false)

  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)

  const intervalRef = useRef<any>(null)
  const pollingRef = useRef<any>(null)

  // =========================================
  // 🔥 POLLING FOR SEGMENTS (MAIN FIX)
  // =========================================
  useEffect(() => {
    if (!id) return

    const fetchSegments = async () => {
      try {
        const res = await api.get(`/segments/project/${id}`)
        const data = res.data || []

        if (data.length > 0) {
          setSegments(data)
          setLoading(false)

          // ✅ STOP polling when ready
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
          }
        }
      } catch (err) {
        console.error("SEGMENTS ERROR:", err)
      }
    }

    // initial call
    fetchSegments()

    // poll every 2s until segments exist
    pollingRef.current = setInterval(fetchSegments, 2000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [id])

  // =========================================
  // COMMENTS POLLING
  // =========================================
  const fetchComments = async (segmentId: string) => {
    try {
      setLoadingComments(true)
      const res = await api.get(`/segments/${segmentId}/comments`)
      setComments(res.data)
    } catch (err) {
      console.error("COMMENTS ERROR:", err)
      setComments([])
    } finally {
      setLoadingComments(false)
    }
  }

  useEffect(() => {
    if (!activeSegmentId) return

    if (intervalRef.current) clearInterval(intervalRef.current)

    intervalRef.current = setInterval(() => {
      fetchComments(activeSegmentId)
    }, 3000)

    return () => clearInterval(intervalRef.current)
  }, [activeSegmentId])

  // =========================================
  // SAVE
  // =========================================
  const debouncedSave = useRef(
    debounce(async (segmentId: string, value: string) => {
      try {
        setSavingMap((prev) => ({ ...prev, [segmentId]: "saving" }))

        await api.patch(`/segments/${segmentId}`, {
          translated_text: value,
        })

        setSavingMap((prev) => ({ ...prev, [segmentId]: "saved" }))

        setTimeout(() => {
          setSavingMap((prev) => ({ ...prev, [segmentId]: "" }))
        }, 1500)
      } catch (err) {
        console.error("SAVE ERROR:", err)
        setSavingMap((prev) => ({ ...prev, [segmentId]: "error" }))
      }
    }, 800)
  ).current

  const handleEdit = (id: string, value: string) => {
    setActiveSegmentId(id)
    fetchComments(id)

    setSegments((prev) =>
      prev.map((seg) =>
        seg.id === id ? { ...seg, translated_text: value } : seg
      )
    )

    debouncedSave(id, value)
  }

  // =========================================
  // COMMENTS
  // =========================================
  const handleAddComment = async () => {
    if (!newComment || !activeSegmentId) return

    try {
      await api.post(`/segments/${activeSegmentId}/comments`, {
        text: newComment,
      })

      setNewComment("")
      fetchComments(activeSegmentId)
    } catch (err) {
      console.error("ADD COMMENT ERROR:", err)
    }
  }

  const handleResolveComment = async (commentId: string) => {
    if (!activeSegmentId) return

    try {
      await api.patch(`/segments/${commentId}/resolve`)
      fetchComments(activeSegmentId)
    } catch (err) {
      console.error("RESOLVE ERROR:", err)
    }
  }

  // =========================================
  // EXPORT
  // =========================================
  const handleExport = async (type: "pdf" | "docx") => {
    if (!id) return

    try {
      setExporting(true)

      const url =
        type === "pdf"
          ? `/projects/${id}/export/pdf`
          : `/projects/${id}/export`

      const res = await api.get(url, {
        responseType: "blob",
      })

      const blob = new Blob([res.data])
      const downloadUrl = window.URL.createObjectURL(blob)

      const link = document.createElement("a")
      link.href = downloadUrl
      link.download =
        type === "pdf" ? "translation.pdf" : "translation.docx"

      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (err) {
      console.error("EXPORT ERROR:", err)
    } finally {
      setExporting(false)
      setExportOpen(false)
    }
  }

  // =========================================
  // UI STATES
  // =========================================
  if (!id) return <div className="p-6">Invalid project</div>

  if (loading) {
    return (
      <div className="p-6 text-gray-500">
        Preparing translation... please wait
      </div>
    )
  }

  if (!segments.length) {
    return (
      <div className="p-6 text-gray-500">
        Still processing… (worker running)
      </div>
    )
  }

  // =========================================
  // MAIN UI
  // =========================================
  return (
    <div className="h-screen flex flex-col bg-gray-100">

      <div className="border-b px-8 py-5 flex items-center justify-between bg-white shadow-sm">
        <div>
          <h1 className="text-xl font-semibold">Translation Editor</h1>
          <p className="text-sm text-gray-500">
            {segments.length} segments
          </p>
        </div>

        <div className="flex items-center gap-3 relative">
          <button
            onClick={() => setExportOpen(!exportOpen)}
            className="px-4 py-2 text-sm border rounded-lg"
          >
            {exporting ? "Exporting..." : "Export"}
          </button>

          {exportOpen && (
            <div className="absolute right-0 mt-2 w-44 bg-white border rounded-lg shadow-lg z-50">
              <button onClick={() => handleExport("docx")} className="block w-full px-4 py-2 text-sm hover:bg-gray-100">
                Export DOCX
              </button>
              <button onClick={() => handleExport("pdf")} className="block w-full px-4 py-2 text-sm hover:bg-gray-100">
                Export PDF
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 grid grid-cols-[1fr_1fr_320px] overflow-hidden">

        {/* LEFT */}
        <div className="overflow-y-auto border-r p-6 space-y-4 bg-gray-50">
          {segments.map((seg: any, i: number) => (
            <div key={seg.id} className="p-5 rounded-xl border bg-white">
              <p className="text-xs text-gray-400">Segment {i + 1}</p>
              <p>{seg.source_text}</p>
            </div>
          ))}
        </div>

        {/* RIGHT */}
        <div className="overflow-y-auto p-6 space-y-4 bg-gray-50">
          {segments.map((seg: any) => (
            <div key={seg.id} className="p-5 rounded-xl border bg-white">
              <textarea
                value={seg.translated_text || ""}
                onFocus={() => {
                  setActiveSegmentId(seg.id)
                  fetchComments(seg.id)
                }}
                onChange={(e) => handleEdit(seg.id, e.target.value)}
                className="w-full border rounded p-3"
              />
            </div>
          ))}
        </div>

        {/* COMMENTS */}
        <div className="border-l bg-white flex flex-col">
          <div className="flex-1 p-4 space-y-3 overflow-y-auto">
            {comments.map((c: any) => (
              <div key={c.id} className="p-3 border rounded">
                <p>{c.text}</p>
                {!c.resolved ? (
                  <button onClick={() => handleResolveComment(c.id)} className="text-xs text-green-600 mt-2">
                    Resolve
                  </button>
                ) : (
                  <p className="text-xs text-green-600">✓ Resolved</p>
                )}
              </div>
            ))}
          </div>

          {activeSegmentId && (
            <div className="p-4 border-t">
              <textarea
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                className="w-full border p-2 mb-2"
              />
              <button onClick={handleAddComment} className="w-full bg-blue-600 text-white py-2">
                Add Comment
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}