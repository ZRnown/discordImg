"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import Joyride, {
  ACTIONS,
  CallBackProps,
  EVENTS,
  STATUS,
  type Placement,
  type Step as JoyrideStep,
  type TooltipRenderProps,
} from "react-joyride"
import { AlertCircle, ArrowLeft, ArrowRight, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { TutorialStep } from "@/lib/tutorial-steps"

type TutorialTourProps = {
  open: boolean
  steps: TutorialStep[]
  stepIndex: number
  currentView: string
  onClose: () => void
  onStepIndexChange: (index: number) => void
  onCurrentViewChange: (view: string) => void
}

type TourTone = "cyan" | "emerald" | "amber" | "violet" | "rose" | "slate"

const toneClasses: Record<TourTone, { strip: string; badge: string; panel: string; border: string; soft: string }> = {
  cyan: {
    strip: "from-cyan-300 via-sky-300 to-cyan-400",
    badge: "text-cyan-700 border-cyan-200 bg-cyan-50",
    panel: "from-cyan-50 to-sky-50",
    border: "border-cyan-200",
    soft: "bg-cyan-50/80",
  },
  emerald: {
    strip: "from-emerald-300 via-teal-300 to-emerald-400",
    badge: "text-emerald-700 border-emerald-200 bg-emerald-50",
    panel: "from-emerald-50 to-teal-50",
    border: "border-emerald-200",
    soft: "bg-emerald-50/80",
  },
  amber: {
    strip: "from-amber-200 via-orange-200 to-amber-300",
    badge: "text-amber-700 border-amber-200 bg-amber-50",
    panel: "from-amber-50 to-orange-50",
    border: "border-amber-200",
    soft: "bg-amber-50/80",
  },
  violet: {
    strip: "from-violet-300 via-fuchsia-300 to-violet-400",
    badge: "text-violet-700 border-violet-200 bg-violet-50",
    panel: "from-violet-50 to-fuchsia-50",
    border: "border-violet-200",
    soft: "bg-violet-50/80",
  },
  rose: {
    strip: "from-rose-300 via-pink-300 to-rose-400",
    badge: "text-rose-700 border-rose-200 bg-rose-50",
    panel: "from-rose-50 to-pink-50",
    border: "border-rose-200",
    soft: "bg-rose-50/80",
  },
  slate: {
    strip: "from-slate-200 via-slate-300 to-slate-400",
    badge: "text-slate-700 border-slate-200 bg-slate-50",
    panel: "from-slate-50 to-white",
    border: "border-slate-200",
    soft: "bg-slate-50/80",
  },
}

const iconShapeClasses = {
  pill: "rounded-full",
  card: "rounded-2xl",
  ring: "rounded-full",
  diamond: "rounded-2xl",
  arc: "rounded-2xl",
}

const placementByView: Partial<Record<string, Placement>> = {
  dashboard: "bottom",
  accounts: "right",
  scraper: "left",
  "image-search": "left",
  shops: "right",
  users: "right",
  logs: "top",
}

function TutorialTooltip({
  backProps,
  closeProps,
  continuous,
  index,
  isLastStep,
  primaryProps,
  skipProps,
  step,
  tooltipProps,
  size,
}: TooltipRenderProps) {
  const meta = (step.data ?? {}) as {
    shape?: "pill" | "card" | "ring" | "diamond" | "arc"
    tone?: TourTone
    alert?: string
    hint?: string
    label?: string
  }
  const tone = toneClasses[meta.tone ?? "cyan"]
  const progress = size > 0 ? ((index + 1) / size) * 100 : 0

  return (
    <div
      ref={tooltipProps.ref}
      role={tooltipProps.role}
      aria-modal={tooltipProps["aria-modal"]}
      className={cn(
        "relative w-[min(430px,calc(100vw-1rem))] overflow-hidden rounded-2xl border bg-white text-slate-900 shadow-[0_20px_80px_rgba(15,23,42,0.14)]",
        tone.border,
      )}
    >
      <div className={cn("absolute inset-x-0 top-0 h-1 bg-gradient-to-r", tone.strip)} />

      <div className="relative p-4 lg:p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-3">
            <div className={cn("inline-flex items-center gap-2 border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em]", tone.badge)}>
              <Sparkles className="size-3.5" />
              {meta.label || "LinkRadar 引导"}
            </div>
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-[0.25em] text-slate-400">
                Step {index + 1} / {size}
              </div>
              <h3 className="max-w-[22rem] text-[22px] font-semibold leading-tight lg:text-[24px]">
                {step.title}
              </h3>
            </div>
          </div>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 rounded-full border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            {...closeProps}
          >
            <X className="size-4" />
          </Button>
        </div>

        <div className="mt-5">
          <div className="h-1.5 rounded-full bg-slate-100">
            <div
              className={cn("h-full rounded-full bg-gradient-to-r", tone.strip)}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className={cn("mt-4 rounded-xl border p-3.5", tone.border, "bg-gradient-to-br", tone.panel)}>
          <p className="text-sm leading-6 text-slate-700">{step.content}</p>
          {meta.hint && <p className="mt-2 text-xs leading-5 text-slate-500">{meta.hint}</p>}
        </div>

        {meta.alert && (
          <div className={cn("mt-3 flex gap-3 rounded-xl border p-3", tone.border, tone.soft)}>
            <div className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center", iconShapeClasses[meta.shape ?? "card"], tone.border, "bg-white")}>
              <AlertCircle className="size-4 text-slate-700" />
            </div>
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-[0.2em] text-slate-400">提示</div>
              <div className="text-sm leading-6 text-slate-700">{meta.alert}</div>
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <div className="text-xs text-slate-500">
            {continuous ? "连续引导" : "单步引导"}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-8 border-slate-200 bg-white px-3 text-slate-700 hover:bg-slate-50 hover:text-slate-900"
              {...skipProps}
            >
              跳过
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 border-slate-200 bg-white px-3 text-slate-700 hover:bg-slate-50 hover:text-slate-900"
              {...backProps}
              disabled={index === 0}
            >
              <ArrowLeft className="mr-1.5 size-4" />
              上一步
            </Button>
            <Button
              size="sm"
              className="h-8 bg-slate-900 px-3 font-semibold text-white hover:bg-slate-800"
              {...primaryProps}
            >
              {isLastStep ? "完成" : "下一步"}
              <ArrowRight className="ml-1.5 size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function TutorialTour({
  open,
  steps,
  stepIndex,
  currentView,
  onClose,
  onStepIndexChange,
  onCurrentViewChange,
}: TutorialTourProps) {
  const [ready, setReady] = useState(false)
  const lastAnnouncedStepIdRef = useRef<string | null>(null)

  const currentStep = steps[stepIndex]

  const joyrideSteps = useMemo<JoyrideStep[]>(() => {
    return steps.map((step, index) => ({
      target: step.selector,
      content: step.description,
      title: step.title,
      placement: step.placement ?? placementByView[step.view] ?? "bottom",
      disableBeacon: true,
      hideFooter: true,
      spotlightClicks: false,
      spotlightPadding: step.spotlightPadding ?? (index === 0 ? 14 : 10),
      disableScrolling: false,
      isFixed: true,
      data: {
        shape: step.shape ?? "card",
        tone: step.tone ?? "cyan",
        alert: step.alert,
        hint: step.note,
        label: step.label,
        view: step.view,
      },
    }))
  }, [steps])

  useEffect(() => {
    if (!open || !currentStep) {
      setReady(false)
      lastAnnouncedStepIdRef.current = null
      return
    }

    if (currentStep.view && currentStep.view !== currentView) {
      setReady(false)
      onCurrentViewChange(currentStep.view)
      return
    }

    setReady(false)
    let cancelled = false
    let observer: MutationObserver | null = null

    const resolveTarget = () => {
      if (cancelled || typeof document === "undefined") {
        return false
      }

      const target = document.querySelector(currentStep.selector)
      if (target instanceof HTMLElement) {
        setReady(true)
        target.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" })
        observer?.disconnect()
        return true
      }

      return false
    }

    if (resolveTarget()) {
      return
    }

    observer = new MutationObserver(() => {
      resolveTarget()
    })
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
    })

    const timeout = window.setTimeout(() => {
      if (!cancelled) {
        resolveTarget()
      }
    }, 8000)

    return () => {
      cancelled = true
      observer?.disconnect()
      window.clearTimeout(timeout)
    }
  }, [open, currentStep, currentView, onCurrentViewChange])

  useEffect(() => {
    if (!open || !ready || !currentStep) return
    if (lastAnnouncedStepIdRef.current === currentStep.id) return

    lastAnnouncedStepIdRef.current = currentStep.id
    toast(currentStep.title, {
      description: currentStep.alert || currentStep.note || currentStep.description,
      duration: 3500,
    })
  }, [open, ready, currentStep])

  const handleJoyrideCallback = (data: CallBackProps) => {
    const { action, index, status, type } = data

    if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      onClose()
      return
    }

    if (type === EVENTS.STEP_AFTER || type === EVENTS.TARGET_NOT_FOUND) {
      const delta = action === ACTIONS.PREV ? -1 : 1
      const nextIndex = Math.max(0, Math.min(index + delta, steps.length - 1))
      onStepIndexChange(nextIndex)
    }
  }

  if (!open || !ready || !currentStep) {
    return null
  }

  return (
    <Joyride
      continuous
      callback={handleJoyrideCallback}
      run={open && ready}
      scrollToFirstStep
      scrollOffset={120}
      showProgress
      showSkipButton
      stepIndex={stepIndex}
      steps={joyrideSteps}
      disableOverlayClose
      disableCloseOnEsc={false}
      spotlightClicks={false}
      styles={{
        options: {
          zIndex: 240,
          primaryColor: "#0f172a",
          textColor: "#0f172a",
          overlayColor: "rgba(15, 23, 42, 0.18)",
          spotlightShadow: "0 0 0 1px rgba(148, 163, 184, 0.16), 0 0 0 9999px rgba(15, 23, 42, 0.18)",
        },
      }}
      tooltipComponent={TutorialTooltip}
    />
  )
}
