export interface DesktopSessionUser {
  id: number
  username: string
  role: string
  shops: string[]
}

type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<{
  ok: boolean
  json(): Promise<any>
}>

type WaitForDesktopUserOptions = {
  fetchImpl?: FetchLike
  maxAttempts?: number
  delayMs?: number
  sleep?: (ms: number) => Promise<void>
}

export const DESKTOP_FALLBACK_USER: DesktopSessionUser = {
  id: 1,
  username: "desktop",
  role: "admin",
  shops: [],
}

const defaultSleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms)
  })

const normalizeUser = (value: any): DesktopSessionUser | null => {
  if (!value || typeof value !== "object") {
    return null
  }

  const id = Number(value.id)
  const username = String(value.username || "").trim()
  const role = String(value.role || "").trim()
  const shops = Array.isArray(value.shops)
    ? value.shops.map((shop: unknown) => String(shop))
    : []

  if (!Number.isFinite(id) || !username || !role) {
    return null
  }

  return { id, username, role, shops }
}

export function resolveDesktopUser({
  desktopMode,
  currentUser,
}: {
  desktopMode: boolean
  currentUser?: DesktopSessionUser | null
}): DesktopSessionUser | null {
  const normalized = normalizeUser(currentUser)
  if (normalized) {
    return normalized
  }
  return desktopMode ? DESKTOP_FALLBACK_USER : null
}

export async function waitForDesktopUser({
  fetchImpl = fetch as FetchLike,
  maxAttempts = 40,
  delayMs = 500,
  sleep = defaultSleep,
}: WaitForDesktopUserOptions = {}): Promise<DesktopSessionUser | null> {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const response = await fetchImpl("/api/auth/me", {
        credentials: "include",
      })
      if (response.ok) {
        const payload = await response.json().catch(() => ({}))
        const user = normalizeUser(payload?.user)
        if (user) {
          return user
        }
      }
    } catch {
      // Desktop backend may still be starting up.
    }

    if (attempt < maxAttempts - 1) {
      await sleep(delayMs)
    }
  }

  return null
}
