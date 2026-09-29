"use client"

import { useEffect, useRef, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"

type Found = { name: string; kind: "merge" | "token" | "field"; field: string; label: string; value: string }
type CheckResult = {
  fields: Found[]
  unknown: { name: string; kind: "merge" | "token" }[]
  dropped: { what: string; count: number }[]
  notes: string[]
  example: { document: string; file_name: string }
}

const PREVIEW_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; background: transparent; font-family: 'Times New Roman', Times, serif; }
body { zoom: var(--zoom, 0.6); }
.docx-wrapper { padding: 0 !important; background: transparent !important; }
section.docx { margin: 0 auto 12px !important; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); }
</style></head><body></body></html>`

export function fieldCode(name: string, kind: string) {
  if (kind === "token") return `{{${name}}}`
  if (kind === "field") return `${name} field`
  return `«${name}»`
}

export default function TemplateCheck({
  certId,
  fileName,
  isDefault,
  onClose,
  onToggleDefault,
}: {
  certId: string
  fileName: string
  isDefault: boolean
  onClose: () => void
  onToggleDefault: () => void
}) {
  const [check, setCheck] = useState<CheckResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewReady, setPreviewReady] = useState(false)
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setCheck(null)
    setError(null)
    api
      .get<CheckResult>(`/certifications/${certId}/check`)
      .then((res) => {
        if (!cancelled) setCheck(res.data)
      })
      .catch((err) => {
        if (!cancelled) setError(apiErrorDetail(err, "Couldn't read this template."))
      })
    return () => {
      cancelled = true
    }
  }, [certId])

  useEffect(() => {
    let cancelled = false
    const host = hostRef.current
    if (!host) return
    setPreviewReady(false)
    setPreviewError(null)
    ;(async () => {
      try {
        const [{ renderAsync }, res] = await Promise.all([
          import("docx-preview"),
          api.get<ArrayBuffer>(`/certifications/${certId}/preview`, { responseType: "arraybuffer" }),
        ])
        if (cancelled) return
        host.replaceChildren()
        const iframe = document.createElement("iframe")
        iframe.title = "Certification page preview"
        Object.assign(iframe.style, { width: "100%", border: "0", display: "block", background: "transparent" })
        await new Promise<void>((resolve) => {
          iframe.addEventListener("load", () => resolve(), { once: true })
          host.appendChild(iframe)
          if (iframe.contentDocument?.readyState === "complete") resolve()
        })
        const idoc = iframe.contentDocument
        if (!idoc || cancelled) return
        idoc.open()
        idoc.write(PREVIEW_HTML)
        idoc.close()
        await renderAsync(res.data, idoc.body, undefined, {
          inWrapper: true,
          breakPages: true,
          ignoreLastRenderedPageBreak: true,
          experimental: true,
          useBase64URL: true,
          renderHeaders: true,
          renderFooters: true,
        })
        if (cancelled) return
        const page = idoc.querySelector<HTMLElement>("section.docx")
        const width = page?.offsetWidth || 794
        const zoom = Math.min(1, (host.clientWidth - 8) / width)
        idoc.documentElement.style.setProperty("--zoom", String(zoom))
        iframe.style.height = `${Math.ceil(idoc.body.scrollHeight * zoom) + 8}px`
        setPreviewReady(true)
      } catch (err) {
        if (!cancelled) setPreviewError(apiErrorDetail(err, "Couldn't render the preview."))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [certId])

  const muted = { color: "#8a8270" }

  return (
    <section className="rounded-2xl" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
      <header
        className="flex items-center justify-between gap-3 flex-wrap px-5 py-4"
        style={{ borderBottom: "1px solid #f1e8d1" }}
      >
        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
            TEMPLATE CHECK
          </div>
          <div className="font-semibold truncate" style={{ color: "#1f2a2e" }} title={fileName}>
            {fileName}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleDefault}
            className="px-3.5 py-1.5 rounded-full text-sm font-semibold"
            style={
              isDefault
                ? { background: "#cfe6e2", color: "#0a5e58", border: "1px solid #b7dad4" }
                : { background: "#0a7870", color: "#fff", border: "1px solid #0a7870" }
            }
          >
            {isDefault ? "Default template" : "Use as default"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-full text-sm font-semibold"
            style={{ background: "#fff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
          >
            Close
          </button>
        </div>
      </header>

      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4 min-w-0">
          {error && (
            <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
              {error}
            </div>
          )}
          {!check && !error && (
            <div className="text-sm" style={muted}>
              Reading the template…
            </div>
          )}
          {check && (
            <>
              <div>
                <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
                  FILLED AUTOMATICALLY · {check.fields.length}
                </div>
                {check.fields.length === 0 ? (
                  <p className="text-sm" style={muted}>
                    No merge fields or tokens found. The page is used as it is.
                  </p>
                ) : (
                  <div className="rounded-xl overflow-x-auto" style={{ border: "1px solid #f1e8d1" }}>
                    <table className="w-full text-sm">
                      <thead>
                        <tr style={{ background: "#faf5ee", color: "#9a9178" }} className="text-[11px] tracking-[0.1em]">
                          <th className="text-left font-semibold px-3 py-2">IN YOUR FILE</th>
                          <th className="text-left font-semibold px-3 py-2">FILLED WITH</th>
                          <th className="text-left font-semibold px-3 py-2">EXAMPLE</th>
                        </tr>
                      </thead>
                      <tbody>
                        {check.fields.map((f) => (
                          <tr key={`${f.kind}:${f.name}`} style={{ borderTop: "1px solid #f4ecd6" }}>
                            <td className="px-3 py-2 font-mono text-[12px]" style={{ color: "#1f2a2e" }}>
                              {fieldCode(f.name, f.kind)}
                            </td>
                            <td className="px-3 py-2" style={{ color: "#4a4638" }}>
                              {f.label}
                            </td>
                            <td className="px-3 py-2" style={{ color: f.value ? "#1f2a2e" : "#b0a88f" }}>
                              {f.value || "empty for this project"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="text-[11px] mt-2" style={muted}>
                  Example: your details on “{check.example.document}” ({check.example.file_name}).
                </p>
              </div>

              {check.unknown.length > 0 && (
                <div className="rounded-xl px-4 py-3" style={{ background: "#fbf1dc", border: "1px solid #f0dcaa" }}>
                  <div className="text-[11px] font-semibold tracking-[0.14em] mb-1.5" style={{ color: "#7a5a10" }}>
                    NOT RECOGNISED · {check.unknown.length}
                  </div>
                  <div className="flex flex-wrap gap-1.5 mb-1.5">
                    {check.unknown.map((u) => (
                      <code
                        key={`${u.kind}:${u.name}`}
                        className="text-[12px] px-1.5 py-0.5 rounded"
                        style={{ background: "#f6e3b8", color: "#5c430b" }}
                      >
                        {fieldCode(u.name, u.kind)}
                      </code>
                    ))}
                  </div>
                  <p className="text-[12px]" style={{ color: "#7a5a10" }}>
                    Shown as written on the page. Rename them to a supported name, or type the text in the editor.
                  </p>
                </div>
              )}

              {check.dropped.length > 0 && (
                <div className="rounded-xl px-4 py-3" style={{ background: "#f7ece8", border: "1px solid #ecd2c9" }}>
                  <div className="text-[11px] font-semibold tracking-[0.14em] mb-1.5" style={{ color: "#7a2f24" }}>
                    LEFT OUT
                  </div>
                  <ul className="text-[13px] space-y-0.5" style={{ color: "#5e2a20" }}>
                    {check.dropped.map((d) => (
                      <li key={d.what}>
                        {d.what}
                        {d.count > 1 ? ` (${d.count})` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {check.notes.length > 0 && (
                <ul className="text-[12px] space-y-1" style={muted}>
                  {check.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
            PREVIEW
          </div>
          <div className="rounded-xl p-3" style={{ background: "#f3efe6", border: "1px solid #ece3cc" }}>
            {!previewReady && !previewError && (
              <div className="text-sm py-10 text-center" style={muted}>
                Rendering…
              </div>
            )}
            {previewError && (
              <div className="text-sm py-10 text-center" style={{ color: "#7a2f24" }}>
                {previewError}
              </div>
            )}
            <div ref={hostRef} />
          </div>
        </div>
      </div>
    </section>
  )
}
