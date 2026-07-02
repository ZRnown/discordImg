import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('admin can update a user role through a guarded backend endpoint', () => {
  const appSource = readSource('backend/app.py')
  const databaseSource = readSource('backend/database.py')

  assert.match(appSource, /@app\.route\('\/api\/users\/<int:user_id>\/role', methods=\['PUT'\]\)/)
  assert.match(appSource, /role not in \('admin', 'user'\)/)
  assert.match(appSource, /current_user\['id'\] == user_id and role != 'admin'/)
  assert.match(appSource, /db\.update_user_role\(user_id, role\)/)
  assert.match(databaseSource, /def update_user_role\(self, user_id: int, role: str\) -> bool:/)
  assert.match(databaseSource, /UPDATE users[\s\S]*SET role = \?, updated_at = CURRENT_TIMESTAMP[\s\S]*WHERE id = \?/)
})

test('frontend user permissions dialog includes role editing and proxy route', () => {
  const usersViewSource = readSource('frontend/components/users-view.tsx')
  const routeSource = readSource('frontend/app/api/users/[id]/role/route.ts')

  assert.match(usersViewSource, /handleSaveUserPermissions/)
  assert.match(usersViewSource, /fetch\(`\/api\/users\/\$\{editingUser\.id\}\/role`/)
  assert.match(usersViewSource, /<Label>角色<\/Label>/)
  assert.match(usersViewSource, /<SelectItem value="admin">管理员<\/SelectItem>/)
  assert.match(routeSource, /BACKEND_URL.*\/api\/users\/\$\{userId\}\/role/)
})
