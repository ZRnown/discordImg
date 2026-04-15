export type DesktopBootstrapLogEntry = {
  timestamp?: string
  level?: string
  message?: string
  raw_line?: string
}

export type DesktopHealthInfo = {
  desktop_backend?: boolean
  single_user?: boolean
  license_required?: boolean
  ai_model_ready?: boolean
  feature_extractor_error?: string | null
  pid?: number
}

type StepState = "done" | "active" | "pending" | "error"

export type DesktopBootstrapStep = {
  label: string
  detail: string
  state: StepState
}

export type DesktopBootstrapSummary = {
  title: string
  description: string
  hint: string
  steps: DesktopBootstrapStep[]
}

const getLogLine = (entry: DesktopBootstrapLogEntry) =>
  String(entry.raw_line || entry.message || "").trim()

export function inferDesktopBootstrapHint({
  bootstrapError,
  desktopHealth,
  logs,
}: {
  bootstrapError?: string | null
  desktopHealth?: DesktopHealthInfo | null
  logs?: DesktopBootstrapLogEntry[]
}): string {
  const lines = (logs || []).map(getLogLine).filter(Boolean)
  const joined = lines.join("\n").toLowerCase()

  if (desktopHealth?.feature_extractor_error) {
    return `AI 初始化报错：${desktopHealth.feature_extractor_error}`
  }

  if (
    joined.includes("huggingface.co") ||
    joined.includes("processor_config.json") ||
    joined.includes("retrying in") ||
    joined.includes("siglip2-base-patch16-224")
  ) {
    return "后端卡在 Hugging Face 模型下载，这会拖住 5001 端口启动。"
  }

  if (
    joined.includes("address already in use") ||
    joined.includes("only one usage of each socket address") ||
    joined.includes("10048") ||
    joined.includes("port 5001")
  ) {
    return "5001 端口可能被别的进程占用了。"
  }

  if (joined.includes("no module named")) {
    return "后端 sidecar 缺少运行依赖，启动过程提前中断了。"
  }

  if (bootstrapError) {
    return bootstrapError
  }

  if (desktopHealth?.desktop_backend) {
    return "本地后端已经响应，正在继续检查桌面会话。"
  }

  return "正在等待本地后端启动并返回桌面会话。"
}

export function buildDesktopBootstrapSummary({
  loading,
  elapsedSeconds,
  backendHealthy,
  sessionReady,
  bootstrapError,
  desktopHealth,
  logs,
}: {
  loading: boolean
  elapsedSeconds: number
  backendHealthy: boolean
  sessionReady: boolean
  bootstrapError?: string | null
  desktopHealth?: DesktopHealthInfo | null
  logs?: DesktopBootstrapLogEntry[]
}): DesktopBootstrapSummary {
  const backendStep: DesktopBootstrapStep = backendHealthy
    ? {
        label: "本地后端进程",
        detail: `5001 已响应${desktopHealth?.pid ? `，PID ${desktopHealth.pid}` : ""}`,
        state: "done",
      }
    : bootstrapError
      ? {
          label: "本地后端进程",
          detail: "5001 还没有成功响应。",
          state: "error",
        }
      : {
          label: "本地后端进程",
          detail: "正在等待 5001 启动。",
          state: "active",
        }

  const sessionStep: DesktopBootstrapStep = sessionReady
    ? {
        label: "桌面会话",
        detail: "已经拿到 /api/auth/me，主界面可进入。",
        state: "done",
      }
    : backendHealthy
      ? {
          label: "桌面会话",
          detail: "后端已启动，正在等待桌面用户会话返回。",
          state: loading ? "active" : "error",
        }
      : {
          label: "桌面会话",
          detail: "需要等本地后端起来后才能检查。",
          state: "pending",
        }

  const aiDetail = desktopHealth?.single_user
    ? "桌面单用户模式下，基础功能启动时会跳过 AI 预热。"
    : desktopHealth?.ai_model_ready
      ? "AI 预热已完成。"
      : "AI 预热还没完成。"

  const aiStep: DesktopBootstrapStep = desktopHealth?.single_user || desktopHealth?.ai_model_ready
    ? {
        label: "AI 预热",
        detail: aiDetail,
        state: "done",
      }
    : desktopHealth?.desktop_backend
      ? {
          label: "AI 预热",
          detail: aiDetail,
          state: "active",
        }
      : {
          label: "AI 预热",
          detail: "等待后端初始化后再判断。",
          state: "pending",
        }

  return {
    title: bootstrapError ? "桌面后端未连接" : "正在连接桌面后端",
    description: `已等待 ${elapsedSeconds} 秒`,
    hint: inferDesktopBootstrapHint({
      bootstrapError,
      desktopHealth,
      logs,
    }),
    steps: [backendStep, sessionStep, aiStep],
  }
}

export function formatDesktopBootstrapDiagnostics({
  loading,
  elapsedSeconds,
  backendHealthy,
  sessionReady,
  bootstrapError,
  desktopHealth,
  logs,
}: {
  loading: boolean
  elapsedSeconds: number
  backendHealthy: boolean
  sessionReady: boolean
  bootstrapError?: string | null
  desktopHealth?: DesktopHealthInfo | null
  logs?: DesktopBootstrapLogEntry[]
}): string {
  const summary = buildDesktopBootstrapSummary({
    loading,
    elapsedSeconds,
    backendHealthy,
    sessionReady,
    bootstrapError,
    desktopHealth,
    logs,
  })

  const lines = [
    `标题: ${summary.title}`,
    `描述: ${summary.description}`,
    `提示: ${summary.hint}`,
    `后端响应: ${backendHealthy ? "是" : "否"}`,
    `桌面会话: ${sessionReady ? "已就绪" : "未就绪"}`,
    `桌面健康: ${JSON.stringify(desktopHealth || {}, null, 2)}`,
    "最近日志:",
    ...((logs || []).map((entry) => getLogLine(entry)).filter(Boolean).slice(-20)),
  ]

  return lines.join("\n")
}
