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

  // 🔥 COMMENTS STATE
  const [comments, setComments] = useState<any[]>([])
  const [newComment, setNewComment] = useState("")
  const [loadingComments, setLoadingComments] = useState(false)

  // 🔥 REALTIME POLLING REF
  const intervalRef = useRef<any>(null)

  useEffect(() => {
    if (!id) return
    fetchSegments()
  }, [id])

  const fetchSegments = async () => {
    try {
      const res = await api.get(`/segments/project/${id}`)
      setSegments(res.data)
    } catch (err) {
      console.error("SEGMENTS ERROR:", err)
    } finally {
      setLoading(false)
    }
  }

  // 🔥 FETCH COMMENTS
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

  // 🔥 REALTIME EFFECT (POLLING)
  useEffect(() => {
    if (!activeSegmentId) return

    // Clear previous interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
    }

    // Poll every 3 seconds
    intervalRef.current = setInterval(() => {
      fetchComments(activeSegmentId)
    }, 3000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [activeSegmentId])

  // 🔥 RESOLVE COMMENT
  const handleResolveComment = async (commentId: string) => {
    if (!activeSegmentId) return

    try {
      await api.patch(`/segments/${commentId}/resolve`)
      fetchComments(activeSegmentId)
    } catch (err) {
      console.error("RESOLVE ERROR:", err)
    }
  }

  const debouncedSave = useRef(
    debounce(async (segmentId: string, value: string) => {
      try {
        setSavingMap((prev) => ({
          ...prev,
          [segmentId]: "saving",
        }))

        await api.patch(`/segments/${segmentId}`, {
          translated_text: value,
        })

        setSavingMap((prev) => ({
          ...prev,
          [segmentId]: "saved",
        }))

        setTimeout(() => {
          setSavingMap((prev) => ({
            ...prev,
            [segmentId]: "",
          }))
        }, 1500)

      } catch (err) {
        console.error("SAVE ERROR:", err)

        setSavingMap((prev) => ({
          ...prev,
          [segmentId]: "error",
        }))
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

  const handleAIRevise = async (seg: any) => {
    try {
      const res = await api.post("/ai/revise", {
        text: seg.translated_text,
        source: seg.source_text,
      })

      const improved = res.data?.text

      if (improved) {
        handleEdit(seg.id, improved)
      }
    } catch (err) {
      console.error("AI ERROR:", err)
    }
  }

  // 🔥 ADD COMMENT (FIXED → NOW REALTIME SAFE)
  const handleAddComment = async () => {
    if (!newComment || !activeSegmentId) return

    try {
      await api.post(`/segments/${activeSegmentId}/comments`, {
        text: newComment,
      })

      setNewComment("")

      // 🔥 ALWAYS REFRESH (no stale UI)
      fetchComments(activeSegmentId)

    } catch (err) {
      console.error("ADD COMMENT ERROR:", err)
    }
  }

  if (!id) return <div className="p-6">Invalid project</div>
  if (loading) return <div className="p-6">Loading...</div>

  if (!segments || segments.length === 0) {
    return <div className="p-6">No segments found</div>
  }

  return (
    <div className="h-screen flex flex-col">

      {/* TOP BAR */}
      <div className="border-b px-6 py-4 flex items-center justify-between bg-white">
        <div>
          <h1 className="font-semibold text-lg">Translation Editor</h1>
          <p className="text-sm text-gray-500">
            {segments.length} segments
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50">
            Export
          </button>

          <button className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Save & Close
          </button>
        </div>
      </div>

      {/* MAIN GRID */}
      <div className="flex-1 grid grid-cols-[1fr_1fr_320px] overflow-hidden">

        {/* LEFT */}
        <div className="overflow-y-auto border-r p-6 space-y-4 bg-gray-50">
          <h2 className="text-sm font-medium text-gray-600 mb-2 sticky top-0 bg-gray-50 py-2 z-10">
            Original Document
          </h2>

          {segments.map((seg: any, index: number) => (
            <div
              key={seg.id}
              className={`p-4 rounded-lg border transition ${
                activeSegmentId === seg.id
                  ? "bg-blue-50 border-blue-500"
                  : "bg-white"
              }`}
            >
              <p className="text-xs text-gray-400 mb-1">
                Segment {index + 1}
              </p>

              <p className="text-sm text-gray-800 whitespace-pre-wrap">
                {seg.source_text}
              </p>
            </div>
          ))}
        </div>

        {/* RIGHT */}
        <div className="overflow-y-auto p-6 space-y-4 bg-gray-50">
          <h2 className="text-sm font-medium text-gray-600 mb-2 sticky top-0 bg-gray-50 py-2 z-10">
            Translated Version (Editable)
          </h2>

          {segments.map((seg: any, index: number) => (
            <div
              key={seg.id}
              className={`p-4 rounded-lg border transition ${
                activeSegmentId === seg.id
                  ? "bg-blue-50 border-blue-500"
                  : "bg-white"
              }`}
            >
              <div className="flex justify-between items-center mb-1">
                <p className="text-xs text-gray-400">
                  Segment {index + 1}
                </p>

                <span className="text-xs text-gray-500">
                  {savingMap[seg.id] === "saving" && "Saving..."}
                  {savingMap[seg.id] === "saved" && "Saved ✓"}
                  {savingMap[seg.id] === "error" && "Error ❌"}
                </span>
              </div>

              <div className="flex justify-end mb-2">
                <button
                  onClick={() => handleAIRevise(seg)}
                  className="text-xs px-3 py-1 bg-purple-100 text-purple-700 rounded hover:bg-purple-200 transition"
                >
                  Ask AI to Revise
                </button>
              </div>

              <textarea
                value={seg.translated_text || ""}
                onFocus={() => {
                  setActiveSegmentId(seg.id)
                  fetchComments(seg.id)
                }}
                onChange={(e) =>
                  handleEdit(seg.id, e.target.value)
                }
                className="w-full text-sm border rounded-md p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none min-h-[80px]"
              />
            </div>
          ))}
        </div>

        {/* COMMENTS PANEL */}
        <div className="border-l bg-white flex flex-col">

          <div className="p-4 border-b">
            <h2 className="text-sm font-semibold">Comments</h2>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">

            {!activeSegmentId && (
              <p className="text-sm text-gray-400">
                Select a segment to view comments
              </p>
            )}

            {loadingComments && (
              <p className="text-sm text-gray-400">Loading...</p>
            )}

            {comments.map((c: any) => {
              const date = new Date(c.created_at)

              return (
                <div
                  key={c.id}
                  className={`flex gap-3 p-3 rounded-lg border transition ${
                    c.resolved
                      ? "bg-green-50 opacity-60"
                      : "bg-gray-50"
                  }`}
                >
                  <div className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-semibold">
                    {c.user?.email
                      ? c.user.email.slice(0, 2).toUpperCase()
                      : "U"}
                  </div>

                  <div className="flex-1">
                    <div className="flex justify-between items-center">
                      <p className="text-sm font-medium text-gray-800">
                        {c.user?.email || "User"}
                      </p>

                      <p className="text-xs text-gray-400">
                        {date.toLocaleTimeString()}
                      </p>
                    </div>

                    <p className="text-sm text-gray-700 mt-1">
                      {c.text}
                    </p>

                    {!c.resolved && (
                      <button
                        onClick={() => handleResolveComment(c.id)}
                        className="text-xs text-green-600 mt-2 hover:underline"
                      >
                        Resolve
                      </button>
                    )}

                    {c.resolved && (
                      <p className="text-xs text-green-600 mt-2 font-medium">
                        ✓ Resolved
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {activeSegmentId && (
            <div className="p-4 border-t">
              <textarea
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                placeholder="Write a comment..."
                className="w-full border rounded-md p-2 text-sm mb-2"
              />

              <button
                onClick={handleAddComment}
                className="w-full bg-blue-600 text-white text-sm py-2 rounded-md hover:bg-blue-700"
              >
                Add Comment
              </button>
            </div>
          )}

        </div>

      </div>
    </div>
  )
}