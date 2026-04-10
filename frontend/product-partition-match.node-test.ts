import test from 'node:test'
import assert from 'node:assert/strict'

test('product partition match helpers normalize matrix-style rules', async () => {
  const mod = await import('./lib/product-partition-match.ts').catch(() => null)

  assert.notEqual(mod, null)
  assert.equal(typeof mod?.normalizeProductPartitionMatchRules, 'function')
  assert.equal(typeof mod?.serializeProductPartitionMatchRules, 'function')
  assert.equal(typeof mod?.getProductPartitionColumnCount, 'function')
  assert.equal(typeof mod?.buildInitialProductPartitionMatchRules, 'function')
  assert.equal(typeof mod?.getProductPartitionColumnLabel, 'function')

  assert.deepEqual(
    mod?.normalizeProductPartitionMatchRules([
      [' B ', ' 30 '],
      ['SP hood', '', null],
      ['', ''],
    ]),
    [
      ['B', '30'],
      ['SP hood', '', ''],
    ],
  )

  assert.equal(
    mod?.serializeProductPartitionMatchRules([
      ['B', '30'],
      ['SP hood'],
    ]),
    JSON.stringify([
      ['B', '30'],
      ['SP hood'],
    ]),
  )

  assert.equal(mod?.getProductPartitionColumnCount([]), 1)
  assert.equal(mod?.getProductPartitionColumnCount([['A'], ['B', '30', 'Dior']]), 3)
  assert.deepEqual(mod?.buildInitialProductPartitionMatchRules('Dior B30'), [['Dior B30']])
  assert.deepEqual(mod?.buildInitialProductPartitionMatchRules(''), [['']])
  assert.equal(mod?.getProductPartitionColumnLabel(0), 'A区')
  assert.equal(mod?.getProductPartitionColumnLabel(3), 'D区')
})
