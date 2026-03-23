export const REPLY_DELAY_STEP = 0.1
export const REPLY_DELAY_MIN = 0.1
export const REPLY_DELAY_MAX = 300

export type ReplyDelayDraft = {
  min: string
  max: string
}

const roundToDelayStep = (value: number) => Math.round(value * 10) / 10

export const getMinimumReplyMaxDelay = (minDelay: number) =>
  roundToDelayStep(Math.max(minDelay + REPLY_DELAY_STEP, REPLY_DELAY_MIN + REPLY_DELAY_STEP))

export const clampReplyDelay = (value: number, min: number, max: number) =>
  roundToDelayStep(Math.min(Math.max(value, min), max))

export const normalizeReplyDelayRange = (minDelay: number, maxDelay: number) => {
  const normalizedMin = clampReplyDelay(minDelay, REPLY_DELAY_MIN, REPLY_DELAY_MAX - REPLY_DELAY_STEP)
  const normalizedMax = clampReplyDelay(
    maxDelay,
    getMinimumReplyMaxDelay(normalizedMin),
    REPLY_DELAY_MAX,
  )

  return {
    minDelay: normalizedMin,
    maxDelay: normalizedMax,
  }
}

export const mergeReplyDelayDraft = (
  current: ReplyDelayDraft | undefined,
  patch: Partial<ReplyDelayDraft>,
): ReplyDelayDraft => ({
  min: patch.min ?? current?.min ?? '',
  max: patch.max ?? current?.max ?? '',
})
