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

const normalizeRowCells = (row: unknown) => (
  Array.isArray(row) ? row.map(cell => coerceCellText(cell)) : [coerceCellText(row)]
)

const normalizeEditableRows = (rawValue: unknown) => {
  const parsed = parseRawRules(rawValue)
  const rows = parsed.map(normalizeRowCells)
  const maxColumns = Math.max(
    rows.reduce((count, row) => Math.max(count, row.length), 0),
    1,
  )

  if (rows.length === 0) {
    return [Array.from({ length: maxColumns }, () => '')]
  }

  return rows.map(row => {
    const nextRow = [...row]
    while (nextRow.length < maxColumns) {
      nextRow.push('')
    }
    return nextRow
  })
}

export const normalizeProductPartitionMatchRules = (rawValue: unknown) => {
  const parsed = parseRawRules(rawValue)
  const normalized: string[][] = []

  parsed.forEach((row) => {
    const cells = normalizeRowCells(row)
    if (cells.some(cell => cell !== '')) {
      normalized.push(cells)
    }
  })

  return normalized
}

export const buildEditableProductPartitionMatchRules = (rawValue: unknown) => (
  normalizeEditableRows(rawValue)
)

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

export const appendProductPartitionMatchRow = (rawValue: unknown) => {
  const rules = buildEditableProductPartitionMatchRules(rawValue)
  const columnCount = Math.max(
    rules.reduce((count, row) => Math.max(count, row.length), 0),
    1,
  )
  return [
    ...rules.map(row => [...row]),
    Array.from({ length: columnCount }, () => ''),
  ]
}

export const removeProductPartitionMatchRow = (rawValue: unknown, rowIndex: number) => {
  const rules = buildEditableProductPartitionMatchRules(rawValue)
  const columnCount = Math.max(
    rules.reduce((count, row) => Math.max(count, row.length), 0),
    1,
  )
  const nextRules = rules
    .filter((_, index) => index !== rowIndex)
    .map(row => [...row])

  if (nextRules.length > 0) {
    return nextRules
  }

  return [Array.from({ length: columnCount }, () => '')]
}

export const appendProductPartitionMatchColumn = (rawValue: unknown) => (
  buildEditableProductPartitionMatchRules(rawValue).map(row => [...row, ''])
)

export const removeProductPartitionMatchColumn = (rawValue: unknown, columnIndex: number) => {
  const rules = buildEditableProductPartitionMatchRules(rawValue)
  const columnCount = Math.max(
    rules.reduce((count, row) => Math.max(count, row.length), 0),
    1,
  )

  if (columnCount <= 1) {
    return rules.map(() => [''])
  }

  const safeIndex = Math.min(Math.max(0, columnIndex), columnCount - 1)
  return rules.map(row => row.filter((_, index) => index !== safeIndex))
}

export const updateProductPartitionMatchCell = (
  rawValue: unknown,
  rowIndex: number,
  columnIndex: number,
  value: string,
) => {
  const rules = buildEditableProductPartitionMatchRules(rawValue).map(row => [...row])

  while (rules.length <= rowIndex) {
    rules.push(Array.from({ length: rules[0]?.length || 1 }, () => ''))
  }

  while (rules[rowIndex].length <= columnIndex) {
    rules[rowIndex].push('')
  }

  rules[rowIndex][columnIndex] = value
  return rules
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
