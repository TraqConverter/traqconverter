// Browsers cancel an upload when the picked file changes or vanishes before it's sent
// (open in Word, or inside iCloud/OneDrive/Dropbox sync). Reading it once, at pick time,
// gives an in-memory copy the browser can always send.
export async function snapshotFile(file: File): Promise<File> {
  const data = await file.arrayBuffer()
  return new File([data], file.name, { type: file.type, lastModified: file.lastModified })
}

export const UNREADABLE_FILE =
  "We couldn't read that file. If it's open in Word, close it; if it's in iCloud Drive or OneDrive, save a copy on your computer. Then pick it again."
