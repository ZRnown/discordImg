const RAW_BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:5001"

export const BACKEND_URL = RAW_BACKEND_URL.replace(/\/+$/, "")

const API_PREFIX = "/api/"

export function toBackendUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith(API_PREFIX) || pathOrUrl === "/api") {
    return `${BACKEND_URL}${pathOrUrl}`
  }
  return pathOrUrl
}

export function installDesktopApiProxy() {
  if (typeof window === "undefined") return
  const marker = "__desktopApiProxyInstalled"
  if ((window as any)[marker]) return

  const nativeFetch = window.fetch.bind(window)

  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url

    const proxiedUrl = toBackendUrl(rawUrl)
    if (proxiedUrl === rawUrl) {
      return nativeFetch(input as any, init)
    }

    const nextInit: RequestInit = {
      ...init,
      credentials: init?.credentials ?? "include",
    }

    return nativeFetch(proxiedUrl, nextInit)
  }) as typeof window.fetch

  ;(window as any)[marker] = true
}
