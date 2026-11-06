import { contextOutput } from "../../shared/audioDevices"
import { makeClickTrack, measureLatency, type LatencyResult } from "./latencyMeasure"
import { TakeAssembler, encodeWav } from "./takeAssembly"

/**
 * Plays the backing track and records the microphone on one audio clock.
 *
 * Both run inside a single AudioContext. The stems are decoded into memory and
 * scheduled to start and stop at exact context frames; the microphone passes
 * through an AudioWorklet that stamps every block with the frame it was
 * rendered at. The take is cut to exactly the frames the backing track
 * played, so its timing needs no measurement: sample i of the take is
 * reference time `start + i / sampleRate`.
 *
 * What remains is the hardware's own round trip (the time from a frame being
 * rendered to it being heard, plus from the voice to the frame it is captured
 * in), which no browser reports reliably.
 */

const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    const channels = input.map((channel) => channel.slice())
    this.port.postMessage({ frame: currentFrame, channels }, channels.map((c) => c.buffer))
    return true
  }
}
registerProcessor("vocalika-capture", Capture)
`

/** Scheduling ahead of the render clock, so a start lands on its exact frame. */
const SCHEDULE_LEAD_SECONDS = 0.1
/** A stop fades over this long instead of cutting mid-waveform (a click). */
const FADE_SECONDS = 0.01

export interface StemUrls {
  vocal?: string
  instrumental?: string
}

interface Segment {
  /** Context frame the backing track (re)started at. */
  frame: number
  /** Reference time at that frame. */
  reference: number
  /** Context frame the segment is scheduled to end at, if known. */
  endFrame: number
}

export class StudioEngine {
  readonly context: AudioContext
  private readonly stems: { vocal?: AudioBuffer; instrumental?: AudioBuffer }
  private readonly vocalGain: GainNode
  /** Everything the singer hears passes here, so a stop can fade it all. */
  private readonly bus: GainNode
  private capture: AudioWorkletNode | null = null
  private microphone: MediaStreamAudioSourceNode | null = null
  private sources: AudioBufferSourceNode[] = []
  private segment: Segment | null = null
  private heldAt = 0
  private take = new TakeAssembler()
  private lastBlockAt = -1
  /** Frame the backing track was last told to stop at. */
  private stopFrame = 0
  /** Length of the last finished take, kept after its blocks are freed. */
  private finishedFrames = 0

  private constructor(context: AudioContext, stems: StudioEngine["stems"]) {
    this.context = context
    this.stems = stems
    this.bus = context.createGain()
    this.bus.connect(contextOutput(context))
    this.vocalGain = context.createGain()
    this.vocalGain.connect(this.bus)
  }

  /** An engine with nothing to play but calibration chirps. */
  static async forCalibration(): Promise<StudioEngine> {
    return await StudioEngine.load({}, { allowEmpty: true })
  }

  /** Decode the stems into memory. Loading a 5-minute song takes well under a second. */
  static async load(urls: StemUrls, options: { allowEmpty?: boolean } = {}): Promise<StudioEngine> {
    const context = new AudioContext({ latencyHint: "interactive" })
    try {
      const decode = async (url?: string) => {
        if (!url) return undefined
        const response = await fetch(url)
        if (!response.ok) throw new Error(`The backing track could not be loaded (${response.status}).`)
        return await context.decodeAudioData(await response.arrayBuffer())
      }
      const [vocal, instrumental] = await Promise.all([decode(urls.vocal), decode(urls.instrumental)])
      if (!vocal && !instrumental && !options.allowEmpty) throw new Error("This song has no backing track to record against.")
      const workletUrl = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "text/javascript" }))
      try {
        await context.audioWorklet.addModule(workletUrl)
      } finally {
        URL.revokeObjectURL(workletUrl)
      }
      return new StudioEngine(context, { vocal, instrumental })
    } catch (reason) {
      void context.close()
      throw reason
    }
  }

  get sampleRate(): number {
    return this.context.sampleRate
  }

  get duration(): number {
    return Math.max(this.stems.vocal?.duration ?? 0, this.stems.instrumental?.duration ?? 0)
  }

  setVoiceLevel(level: number): void {
    this.vocalGain.gain.setTargetAtTime(level, this.context.currentTime, 0.02)
  }

  /**
   * Route the microphone into the capture tap and wait until its blocks flow:
   * a take must not be scheduled before the tap is running.
   */
  async attachMicrophone(stream: MediaStream): Promise<void> {
    this.detachMicrophone()
    if (this.context.state === "suspended") await this.context.resume()
    this.take = new TakeAssembler()
    this.finishedFrames = 0
    this.lastBlockAt = -1
    const capture = new AudioWorkletNode(this.context, "vocalika-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCountMode: "max",
      channelInterpretation: "discrete",
    })
    capture.port.onmessage = (event: MessageEvent<{ frame: number; channels: Float32Array[] }>) => {
      this.lastBlockAt = event.data.frame
      this.take.add(event.data.frame, event.data.channels)
    }
    // The tap has to be part of the rendered graph to run; it outputs silence.
    const silent = this.context.createGain()
    silent.gain.value = 0
    capture.connect(silent).connect(this.context.destination)
    this.microphone = this.context.createMediaStreamSource(stream)
    this.microphone.connect(capture)
    this.capture = capture
    const deadline = performance.now() + 3000
    while (this.lastBlockAt < 0) {
      if (performance.now() > deadline) throw new Error("The microphone did not start delivering audio.")
      await new Promise((resolve) => window.setTimeout(resolve, 10))
    }
  }

  detachMicrophone(): void {
    this.microphone?.disconnect()
    this.capture?.disconnect()
    if (this.capture) this.capture.port.onmessage = null
    this.microphone = null
    this.capture = null
  }

  /**
   * Start (or resume) the backing track at `reference` seconds and the capture
   * with it, both at the same exact frame. Plays until `end` seconds.
   */
  play(reference: number, end: number): void {
    if (this.segment) return
    const rate = this.sampleRate
    const frame = Math.ceil((this.context.currentTime + SCHEDULE_LEAD_SECONDS) * rate)
    const remaining = Math.max(0, Math.min(end, this.duration) - reference)
    const endFrame = frame + Math.round(remaining * rate)
    const when = frame / rate
    this.sources = []
    const start = (buffer: AudioBuffer | undefined, destination: AudioNode) => {
      if (!buffer) return
      const source = this.context.createBufferSource()
      source.buffer = buffer
      source.connect(destination)
      source.start(when, reference)
      source.stop(endFrame / rate)
      this.sources.push(source)
    }
    this.bus.gain.cancelScheduledValues(0)
    this.bus.gain.setValueAtTime(1, when)
    start(this.stems.instrumental, this.bus)
    start(this.stems.vocal, this.vocalGain)
    this.take.open(frame)
    this.segment = { frame, reference, endFrame }
  }

  /** Hold the backing track and the capture at the same frame; returns where. */
  hold(): number {
    const segment = this.segment
    if (!segment) return this.heldAt
    const rate = this.sampleRate
    // Far enough ahead for the fade to be scheduled before it has to start.
    const lead = Math.ceil(FADE_SECONDS * rate) + 256
    const frame = Math.min(segment.endFrame, Math.max(segment.frame, Math.ceil(this.context.currentTime * rate) + lead))
    const stopAt = frame / rate
    this.bus.gain.cancelScheduledValues(0)
    this.bus.gain.setValueAtTime(1, Math.max(this.context.currentTime, stopAt - FADE_SECONDS))
    this.bus.gain.linearRampToValueAtTime(0, stopAt)
    this.stopFrame = frame
    this.sources.forEach((source) => {
      try {
        source.stop(stopAt)
      } catch {
        // Already stopped.
      }
    })
    this.sources = []
    this.take.close(frame)
    this.segment = null
    this.heldAt = segment.reference + (frame - segment.frame) / rate
    return this.heldAt
  }

  /** Whether playback has reached the end it was scheduled for. */
  reachedEnd(): boolean {
    const segment = this.segment
    return !!segment && this.context.currentTime * this.sampleRate >= segment.endFrame
  }

  /** Reference time at the frame being rendered now. */
  position(): number {
    const segment = this.segment
    if (!segment) return this.heldAt
    const frames = Math.min(segment.endFrame, Math.max(segment.frame, this.context.currentTime * this.sampleRate))
    return segment.reference + (frames - segment.frame) / this.sampleRate
  }

  capturedSeconds(): number {
    return (this.take.capturedFrames() || this.finishedFrames) / this.sampleRate
  }

  /**
   * Close the take, then build it with the audio engine paused.
   *
   * Building a take allocates hundreds of megabytes; if the engine is still
   * running then, WebKit's audio thread can stall and the speakers repeat a
   * tiny fragment until it recovers. So: let the fade finish, collect the last
   * frames, pause rendering, and only then build the file.
   */
  async finish(): Promise<File> {
    if (this.segment) this.hold()
    const rate = this.sampleRate
    const deadline = performance.now() + 2000
    while (
      (!this.take.complete() || this.context.currentTime * rate < this.stopFrame + 256)
      && this.capture && performance.now() < deadline
    ) {
      await new Promise((resolve) => window.setTimeout(resolve, 10))
    }
    this.detachMicrophone()
    await this.context.suspend()
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    this.finishedFrames = this.take.capturedFrames()
    const audio = encodeWav(this.take.build(), rate)
    this.take = new TakeAssembler() // free the blocks
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-")
    return new File([audio], `recorded-take-${timestamp}.wav`, { type: "audio/wav" })
  }

  /**
   * Play chirps through the same output path as the backing track and find
   * them in the microphone signal: the round trip every take carries.
   * Returns null when they were not heard clearly enough to trust.
   */
  async measureRoundTrip(): Promise<LatencyResult | null> {
    if (!this.capture) throw new Error("The microphone is not connected.")
    if (this.segment) this.hold()
    const rate = this.sampleRate
    const track = makeClickTrack(rate)
    const buffer = this.context.createBuffer(1, track.length, rate)
    buffer.copyToChannel(track, 0)
    const frame = Math.ceil((this.context.currentTime + SCHEDULE_LEAD_SECONDS) * rate)
    const source = this.context.createBufferSource()
    source.buffer = buffer
    this.bus.gain.cancelScheduledValues(0)
    this.bus.gain.setValueAtTime(1, frame / rate)
    source.connect(this.bus)
    source.start(frame / rate)
    this.take = new TakeAssembler()
    this.take.open(frame)
    this.take.close(frame + track.length)
    const deadline = performance.now() + (track.length / rate) * 1000 + 3000
    while (!this.take.complete()) {
      if (performance.now() > deadline) throw new Error("The microphone stopped delivering audio.")
      await new Promise((resolve) => window.setTimeout(resolve, 20))
    }
    const channels = this.take.build()
    this.take = new TakeAssembler()
    // Whichever input channel the microphone is on: sum them.
    const mono = new Float32Array(channels[0].length)
    channels.forEach((channel) => channel.forEach((value, index) => { mono[index] += value }))
    return measureLatency(mono, rate)
  }

  /** Stop everything without keeping a take. */
  abandon(): void {
    if (this.segment) this.hold()
    this.detachMicrophone()
    this.take = new TakeAssembler()
  }

  close(): void {
    this.abandon()
    void this.context.close()
  }
}
