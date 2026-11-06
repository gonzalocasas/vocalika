/**
 * Builds a take from microphone blocks stamped with the audio clock.
 *
 * The recording studio plays the backing track and captures the microphone in
 * one AudioContext. Every captured block carries the context frame it was
 * rendered at, and the backing track is scheduled to start and stop at exact
 * frames. A capture window is the span of frames during which the backing
 * track was playing; the take is the windows laid end to end. So take sample i
 * belongs to reference time `start + i / sampleRate` by construction, across
 * any number of pauses, with no clock comparison to drift or jitter.
 *
 * Blocks are placed by their frame number, never appended: a block the audio
 * thread skipped leaves silence where it was rather than shifting everything
 * after it earlier.
 */

export interface CaptureWindow {
  /** First frame, inclusive. */
  from: number
  /** End frame, exclusive; null while the window is still open. */
  to: number | null
}

interface Piece {
  /** Frame offset inside its window. */
  offset: number
  channels: Float32Array[]
}

export class TakeAssembler {
  private readonly windows: CaptureWindow[] = []
  private readonly pieces: Piece[][] = []
  private channelCount = 0
  /** One past the last frame received from the audio thread. */
  private received = 0

  open(from: number): void {
    const last = this.windows.at(-1)
    if (last && last.to === null) throw new Error("A capture window is already open")
    if (last && last.to !== null && from < last.to) throw new Error("Capture windows must not overlap")
    this.windows.push({ from, to: null })
    this.pieces.push([])
  }

  close(to: number): void {
    const last = this.windows.at(-1)
    if (!last || last.to !== null) throw new Error("No capture window is open")
    last.to = Math.max(last.from, to)
  }

  get isOpen(): boolean {
    return this.windows.at(-1)?.to === null
  }

  /** Take one block from the audio thread: `channels` start at context frame `frame`. */
  add(frame: number, channels: Float32Array[]): void {
    const length = channels[0]?.length ?? 0
    this.received = Math.max(this.received, frame + (length || 128))
    if (!length) return // No input yet: the window keeps silence there.
    this.channelCount = Math.max(this.channelCount, channels.length)
    this.windows.forEach((window, index) => {
      const start = Math.max(frame, window.from)
      const end = Math.min(frame + length, window.to ?? Number.POSITIVE_INFINITY)
      if (end <= start) return
      this.pieces[index].push({
        offset: start - window.from,
        channels: channels.map((channel) => channel.slice(start - frame, end - frame)),
      })
    })
  }

  /** Frames of take recorded so far (open window counted up to what arrived). */
  capturedFrames(): number {
    return this.windows.reduce((total, window) => {
      const end = Math.min(window.to ?? Number.POSITIVE_INFINITY, this.received)
      return total + Math.max(0, end - window.from)
    }, 0)
  }

  /** Whether every closed window has been fully delivered by the audio thread. */
  complete(): boolean {
    const last = this.windows.at(-1)
    return !!last && last.to !== null && this.received >= last.to
  }

  /** The take, one array per channel (at least one, silent if nothing came). */
  build(): Float32Array[] {
    const total = this.windows.reduce((sum, window) => sum + ((window.to ?? window.from) - window.from), 0)
    const output = Array.from({ length: Math.max(1, this.channelCount) }, () => new Float32Array(total))
    let base = 0
    this.windows.forEach((window, index) => {
      const length = (window.to ?? window.from) - window.from
      for (const piece of this.pieces[index]) {
        const room = Math.min(piece.channels[0].length, length - piece.offset)
        if (room <= 0) continue
        output.forEach((target, channel) => {
          const source = piece.channels[channel] ?? piece.channels[0]
          target.set(source.subarray(0, room), base + piece.offset)
        })
      }
      base += length
    })
    return output
  }
}

/** A 24-bit PCM WAV: lossless for a microphone, at a third less than float. */
export function encodeWav(channels: Float32Array[], sampleRate: number): Blob {
  const channelCount = channels.length
  const frames = channels[0]?.length ?? 0
  const bytesPerSample = 3
  const dataBytes = frames * channelCount * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataBytes)
  const view = new DataView(buffer)
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i))
  }
  text(0, "RIFF")
  view.setUint32(4, 36 + dataBytes, true)
  text(8, "WAVE")
  text(12, "fmt ")
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // integer PCM
  view.setUint16(22, channelCount, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * channelCount * bytesPerSample, true)
  view.setUint16(32, channelCount * bytesPerSample, true)
  view.setUint16(34, 8 * bytesPerSample, true)
  text(36, "data")
  view.setUint32(40, dataBytes, true)
  const bytes = new Uint8Array(buffer)
  let position = 44
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channelCount; channel += 1) {
      const value = Math.max(-1, Math.min(1, channels[channel][frame]))
      const integer = Math.round(value < 0 ? value * 0x800000 : value * 0x7fffff)
      bytes[position] = integer & 0xff
      bytes[position + 1] = (integer >> 8) & 0xff
      bytes[position + 2] = (integer >> 16) & 0xff
      position += 3
    }
  }
  return new Blob([buffer], { type: "audio/wav" })
}
