import { api, apiErrorDetail } from "./api"

function fileNameFrom(disposition: string | undefined, fallback: string) {
  const m = /filename="?([^";]+)"?/i.exec(disposition || "")
  return m ? m[1] : fallback
}

// Errors on a blob request arrive as a Blob too, so read the JSON detail out of it.
export async function blobErrorDetail(err: unknown, fallback: string): Promise<string> {
  const raw = (err as { response?: { data?: unknown } })?.response?.data
  if (raw instanceof Blob) {
    try {
      const detail = JSON.parse(await raw.text())?.detail
      if (typeof detail === "string" && detail) return detail
    } catch {
      return fallback
    }
    return fallback
  }
  return apiErrorDetail(err, fallback)
}

export async function downloadFrom(path: string, params: Record<string, string | boolean>, fallbackName: string) {
  const res = await api.get<Blob>(path, { params, responseType: "blob" })
  const href = window.URL.createObjectURL(res.data)
  const a = document.createElement("a")
  a.href = href
  a.download = fileNameFrom(res.headers["content-disposition"], fallbackName)
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(href)
}
