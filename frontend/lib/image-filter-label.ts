const IMAGE_EXTENSION_RE = /\.(avif|bmp|gif|heic|heif|jpe?g|png|svg|webp)$/i

export function formatSelectedImageFileLabel(fileName: string | null | undefined, index: number) {
  const trimmed = typeof fileName === "string" ? fileName.trim() : ""
  if (!trimmed) {
    return `图片 ${index + 1}`
  }

  const normalized = trimmed.replace(IMAGE_EXTENSION_RE, "").trim()
  return normalized || `图片 ${index + 1}`
}
