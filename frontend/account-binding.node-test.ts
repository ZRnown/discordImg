import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildAccountBindingPayload,
  toggleAccountBindingSelection,
} from './lib/utils.ts'

test('buildAccountBindingPayload keeps numeric ids in order and removes duplicates', () => {
  assert.deepEqual(
    buildAccountBindingPayload(['19', '15', '19', '', 'abc', '16']),
    { account_ids: [19, 15, 16] },
  )
})

test('toggleAccountBindingSelection adds and removes account ids', () => {
  assert.deepEqual(toggleAccountBindingSelection([], '15'), ['15'])
  assert.deepEqual(toggleAccountBindingSelection(['15'], '16'), ['15', '16'])
  assert.deepEqual(toggleAccountBindingSelection(['15', '16'], '15'), ['16'])
})
