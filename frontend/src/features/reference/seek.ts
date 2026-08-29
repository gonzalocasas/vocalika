/**
 * Turn a pointer position over the waveform into a playback position.
 *
 * The waveform always draws the whole reference, but playback is bounded by
 * the trimmed range, so a click outside the selection resolves to its nearest
 * edge rather than to a position that would stop immediately.
 */
export function seekTimeAt(
  clientX: number,
  bounds: { left: number; width: number },
  duration: number,
  trimStart: number,
  trimEnd: number,
): number {
  if (bounds.width <= 0 || duration <= 0) return trimStart
  const fraction = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width))
  const time = fraction * duration
  // A degenerate range (start past end) would otherwise invert the clamp.
  const low = Math.min(trimStart, trimEnd)
  const high = Math.max(trimStart, trimEnd)
  return Math.max(low, Math.min(high, time))
}
