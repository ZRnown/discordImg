import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

import {
  buildAccountBindingPayload,
  toggleAccountBindingSelection,
} from './lib/utils.ts'

const readAccountsViewSource = () => {
  const candidates = [
    path.join(process.cwd(), 'frontend/components/accounts-view.tsx'),
    path.join(process.cwd(), 'components/accounts-view.tsx'),
  ]

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return readFileSync(candidate, 'utf8')
    }
  }

  throw new Error(`Could not find accounts-view.tsx in: ${candidates.join(', ')}`)
}

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

test('account binding chips no longer show sender or both role badges', () => {
  const source = readAccountsViewSource()

  assert.doesNotMatch(
    source,
    /binding\.role === 'listener' \? '监听' : binding\.role === 'sender' \? '发送' : '两者'/,
  )
})
