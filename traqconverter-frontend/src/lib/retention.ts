// The API sends naive UTC timestamps.
export function deletionDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })
}

export function deletionNotice(iso: string | null | undefined): string | null {
  const date = deletionDate(iso)
  return date ? `Deleted automatically on ${date}` : null
}
