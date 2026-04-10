const coerceCellText = (value: unknown) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const parseRawRules = (rawValue: unknown): unknown[] => {
  if (rawValue === null || rawValue === undefined) return []

  if (typeof rawValue === 'string') {
    const trimmed = rawValue.trim()
    if (!trimmed) return []
    try {
      const parsed = JSON.parse(trimmed)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  return Array.isArray(rawValue) ? rawValue : []
}

export const normalizeProductPartitionMatchRules = (rawValue: unknown) => {
  const parsed = parseRawRules(rawValue)
  const normalized: string[][] = []

  parsed.forEach((row) => {
    const cells = Array.isArray(row) ? row.map(cell => coerceCellText(cell)) : [coerceCellText(row)]
    if (cells.some(cell => cell !== '')) {
      normalized.push(cells)
    }
  })

  return normalized
}

export const serializeProductPartitionMatchRules = (rawValue: unknown) => JSON.stringify(
  normalizeProductPartitionMatchRules(rawValue),
)

export const getProductPartitionColumnCount = (rules: unknown) => {
  const normalized = normalizeProductPartitionMatchRules(rules)
  const maxColumns = normalized.reduce((count, row) => Math.max(count, row.length), 0)
  return Math.max(maxColumns, 1)
}

export const buildInitialProductPartitionMatchRules = (seedValue: unknown) => {
  const seed = coerceCellText(seedValue)
  return [[seed]]
}

export const getProductPartitionColumnLabel = (index: number) => {
  let current = Math.max(0, Number(index) || 0)
  let label = ''

  do {
    label = String.fromCharCode(65 + (current % 26)) + label
    current = Math.floor(current / 26) - 1
  } while (current >= 0)

  return `${label}区`
}
