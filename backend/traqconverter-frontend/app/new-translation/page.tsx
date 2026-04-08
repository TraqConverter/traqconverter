"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

export default function NewTranslationPage() {
  const router = useRouter()

  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)

  const [sourceLang, setSourceLang] = useState("English")
  const [targetLang, setTargetLang] = useState("Spanish")
  const [model, setModel] = useState("balanced")

  const handleUpload = async () => {
    if (!file || loading) return alert("Please select a file")

    try {
      setLoading(true)

      const formData = new FormData()
      formData.append("file", file)
      formData.append("source_language", sourceLang)
      formData.append("target_language", targetLang)
      formData.append("model", model)

      // ✅ FIX: REMOVE headers (axios handles it)
      const res = await api.post("/projects/upload", formData)

      // ✅ FIX: backend returns project_id, not id
      const projectId = res.data.project_id

      if (!projectId) {
        throw new Error("Invalid response from server")
      }

      // 🚀 Redirect to editor
      router.push(`/editor/${projectId}`)

    } catch (err: any) {
      console.error(err)

      // ✅ Better error message from backend
      const message =
        err?.response?.data?.detail || "Upload failed"

      alert(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-8 space-y-8">

      {/* HEADER */}
      <div>
        <h1 className="text-3xl font-bold">New Translation</h1>
        <p className="text-gray-500">
          Upload your documents and configure translation settings
        </p>
      </div>

      <div className="grid grid-cols-3 gap-6">

        {/* LEFT SIDE */}
        <div className="col-span-2 bg-white p-8 rounded-xl shadow">

          {/* UPLOAD BOX */}
          <div className="border-2 border-dashed rounded-xl p-10 text-center space-y-4">

            <div className="text-4xl">⬆️</div>

            <p className="text-lg font-medium">
              Drag & drop your files here
            </p>

            <p className="text-sm text-gray-500">
              or click to browse from your computer
            </p>

            <input
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="hidden"
              id="fileInput"
            />

            <label
              htmlFor="fileInput"
              className="inline-block bg-blue-600 text-white px-4 py-2 rounded cursor-pointer hover:scale-105 transition"
            >
              Choose Files
            </label>

            {file && (
              <p className="text-sm text-gray-600">
                Selected: {file.name}
              </p>
            )}
          </div>

          {/* FORMATS */}
          <div className="mt-6 text-sm text-gray-500">
            Supported formats:
            <div className="flex gap-2 mt-2 flex-wrap">
              {["PDF", "DOCX", "PPTX", "XLSX", "Images"].map((f) => (
                <span
                  key={f}
                  className="px-3 py-1 bg-gray-100 rounded-full text-xs"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>

          {/* BUTTON */}
          <button
            onClick={handleUpload}
            disabled={!file || loading}
            className="mt-6 w-full bg-blue-600 text-white py-3 rounded-lg disabled:opacity-50 hover:scale-[1.01] transition"
          >
            {loading ? "Uploading..." : "Start Translation"}
          </button>

        </div>

        {/* RIGHT PANEL */}
        <div className="space-y-6">

          {/* LANGUAGE SETTINGS */}
          <div className="bg-white p-6 rounded-xl shadow space-y-4">

            <h2 className="font-semibold">Language Settings</h2>

            <div>
              <label className="text-sm text-gray-500">
                Source Language
              </label>
              <select
                value={sourceLang}
                onChange={(e) => setSourceLang(e.target.value)}
                className="w-full border p-2 rounded mt-1"
              >
                <option value="English">Auto Detect</option>
                <option value="English">English</option>
              </select>
            </div>

            <div>
              <label className="text-sm text-gray-500">
                Target Language
              </label>
              <select
                value={targetLang}
                onChange={(e) => setTargetLang(e.target.value)}
                className="w-full border p-2 rounded mt-1"
              >
                <option value="Spanish">Spanish</option>
                <option value="French">French</option>
                <option value="German">German</option>
              </select>
            </div>

          </div>

          {/* AI MODEL */}
          <div className="bg-white p-6 rounded-xl shadow space-y-4">

            <h2 className="font-semibold">AI Model</h2>

            {/* FAST */}
            <div
              onClick={() => setModel("fast")}
              className={`border rounded-lg p-4 cursor-pointer transition ${
                model === "fast" ? "border-blue-500" : "hover:border-blue-400"
              }`}
            >
              <p className="font-medium">Fast</p>
              <p className="text-sm text-gray-500">
                Quick translations (~2 min)
              </p>
              <p className="text-xs text-blue-600 mt-1">50 credits</p>
            </div>

            {/* BALANCED */}
            <div
              onClick={() => setModel("balanced")}
              className={`p-4 rounded-lg cursor-pointer transition ${
                model === "balanced"
                  ? "border-2 border-blue-500"
                  : "border hover:border-blue-400"
              }`}
            >
              <p className="font-medium">
                Balanced{" "}
                <span className="text-green-600 text-xs">Recommended</span>
              </p>
              <p className="text-sm text-gray-500">
                Best speed & quality (~5 min)
              </p>
              <p className="text-xs text-blue-600 mt-1">100 credits</p>
            </div>

            {/* QUALITY */}
            <div
              onClick={() => setModel("quality")}
              className={`border rounded-lg p-4 cursor-pointer transition ${
                model === "quality" ? "border-blue-500" : "hover:border-blue-400"
              }`}
            >
              <p className="font-medium">High Quality</p>
              <p className="text-sm text-gray-500">
                Maximum accuracy (~10 min)
              </p>
              <p className="text-xs text-blue-600 mt-1">200 credits</p>
            </div>

          </div>

        </div>

      </div>

    </div>
  )
}