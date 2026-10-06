export type ProgressStage = "reading" | "translating" | "rebuilding" | "finishing"

const STAGE_LABELS: Record<ProgressStage, string> = {
  reading: "Reading the document",
  translating: "Translating the text",
  rebuilding: "Rebuilding the layout",
  finishing: "Finishing up",
}

export function stageText(p: { status?: string; progress_stage?: string | null; progress_detail?: string | null }) {
  if ((p.status || "").toUpperCase() === "PENDING") return "Waiting to start"
  if (p.progress_detail) return p.progress_detail
  const stage = p.progress_stage as ProgressStage | null | undefined
  return (stage && STAGE_LABELS[stage]) || "Starting"
}
