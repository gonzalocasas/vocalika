/** All values are seconds. Positive offset is extra lead-in in the take. */
export function recordingOffset(recordedSeconds: number, referenceSeconds: number): number {
  return recordedSeconds - referenceSeconds
}

export function timingIsConsistent(
  offset: number, recordedSeconds: number, referenceSeconds: number,
  otherReferenceSeconds?: number,
): boolean {
  const values = [offset, recordedSeconds, referenceSeconds]
  if (otherReferenceSeconds !== undefined) values.push(otherReferenceSeconds)
  return values.every(Number.isFinite)
    && Math.abs(recordingOffset(recordedSeconds, referenceSeconds) - offset) <= 0.1
    && (otherReferenceSeconds === undefined
      || Math.abs(referenceSeconds - otherReferenceSeconds) <= 0.1)
}
