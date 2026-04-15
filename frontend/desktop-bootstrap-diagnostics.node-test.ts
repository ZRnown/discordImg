import test from "node:test"
import assert from "node:assert/strict"

import {
  buildDesktopBootstrapSummary,
  inferDesktopBootstrapHint,
} from "./lib/desktop-bootstrap-diagnostics.ts"

test("inferDesktopBootstrapHint identifies Hugging Face retry stalls", () => {
  const hint = inferDesktopBootstrapHint({
    logs: [
      {
        raw_line:
          "Retrying in 8s while requesting HEAD https://huggingface.co/google/siglip2-base-patch16-224/resolve/main/processor_config.json",
      },
    ],
  })

  assert.match(hint, /hugging face/i)
})

test("buildDesktopBootstrapSummary marks backend and session as done when desktop session is ready", () => {
  const summary = buildDesktopBootstrapSummary({
    loading: false,
    elapsedSeconds: 3,
    backendHealthy: true,
    sessionReady: true,
    desktopHealth: {
      desktop_backend: true,
      single_user: true,
      pid: 123,
    },
    logs: [],
  })

  assert.equal(summary.steps[0]?.state, "done")
  assert.equal(summary.steps[1]?.state, "done")
  assert.match(summary.steps[2]?.detail || "", /跳过 AI 预热/)
})
