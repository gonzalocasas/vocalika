import { reactive, type Directive } from "vue"

/**
 * Which microphone records and which output plays, chosen once in Settings.
 *
 * Nothing chosen means "whatever the system is set to". A chosen device is
 * remembered by id and by name: browsers re-key device ids per site, so the
 * name is what finds the same headset again when the id no longer matches.
 *
 * WebKit (Safari, the macOS app) shapes how this works, measured on macOS 26:
 * - device names stay hidden until the microphone has been opened on the
 *   page, so a remembered device can only be looked for once it is open;
 * - `setSinkId` exists on media elements but rejects without a user gesture,
 *   and AudioContext has none.
 */

export interface AudioDevice {
  id: string
  label: string
}

const INPUT_KEY = "vocalika.audio.input"
const OUTPUT_KEY = "vocalika.audio.output"

const canChooseOutput =
  typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype

function readRemembered(key: string): AudioDevice | null {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<AudioDevice>
    return typeof value.id === "string" && typeof value.label === "string"
      ? { id: value.id, label: value.label }
      : null
  } catch {
    return null
  }
}

function remember(key: string, device: AudioDevice | null): void {
  try {
    if (device) window.localStorage.setItem(key, JSON.stringify(device))
    else window.localStorage.removeItem(key)
  } catch {
    // Storage can be unavailable; the choice then lasts until the app closes.
  }
}

export const audioDevices = reactive({
  inputs: [] as AudioDevice[],
  outputs: [] as AudioDevice[],
  /** Device names are only revealed once the microphone has been opened. */
  namesKnown: false,
  canChooseOutput,
  /** The singer's choice, or null for the system default. */
  chosenInput: null as AudioDevice | null,
  chosenOutput: null as AudioDevice | null,
  /** The microphone the last recording actually opened. */
  inputInUse: "",
  /** Names of what "system default" currently means, where the browser says. */
  defaultInputLabel: "",
  defaultOutputLabel: "",
  /** Set when a chosen device is not connected and the default stands in. */
  notice: "",
  /** Set when the chosen output could not be switched to. */
  outputNotice: "",
  /** Measured round trips, keyed by device pair (see pairKey). */
  latencies: {} as Record<string, MeasuredLatency>,
})

export interface MeasuredLatency {
  seconds: number
  measuredAt: string
}

const LATENCY_KEY = "vocalika.audio.latency"

if (typeof window !== "undefined") {
  audioDevices.chosenInput = readRemembered(INPUT_KEY)
  audioDevices.chosenOutput = canChooseOutput ? readRemembered(OUTPUT_KEY) : null
  try {
    const stored = JSON.parse(window.localStorage.getItem(LATENCY_KEY) ?? "{}") as Record<string, MeasuredLatency>
    if (stored && typeof stored === "object") audioDevices.latencies = stored
  } catch {
    // No measurements yet.
  }
}

// --- Round-trip latency -------------------------------------------------------

/**
 * The device pair a latency belongs to. Named by what is actually in use, so
 * "system default" measured on the Scarlett does not apply to AirPods later.
 */
export function pairKey(): string {
  const input = audioDevices.chosenInput?.label || audioDevices.inputInUse || audioDevices.defaultInputLabel || "default input"
  const output = audioDevices.chosenOutput?.label || audioDevices.defaultOutputLabel || "system output"
  return `${input} → ${output}`
}

export function latencyForPair(key = pairKey()): MeasuredLatency | null {
  return audioDevices.latencies[key] ?? null
}

export function rememberLatency(seconds: number, key = pairKey()): void {
  audioDevices.latencies = { ...audioDevices.latencies, [key]: { seconds, measuredAt: new Date().toISOString() } }
  try {
    window.localStorage.setItem(LATENCY_KEY, JSON.stringify(audioDevices.latencies))
  } catch {
    // Kept for this session only.
  }
}

/**
 * Apply the remembered devices as soon as the app starts.
 *
 * WebKit reveals device ids only to a page that has used the microphone, so
 * until then a saved output cannot be switched to and the system default
 * plays instead. Opening the microphone for a moment at start-up reveals
 * them; only done when a device was actually chosen.
 */
export async function primeDevices(): Promise<void> {
  if (!audioDevices.chosenInput && !audioDevices.chosenOutput) return
  if (!navigator.mediaDevices?.getUserMedia) return
  try {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true })
    await listDevices()
    probe.getTracks().forEach((track) => track.stop())
  } catch {
    // No permission yet: devices are revealed the first time the mic is used.
  }
}

/** The connected device a remembered choice refers to: by id, else by name. */
export function resolve(remembered: AudioDevice | null, devices: AudioDevice[]): AudioDevice | null {
  if (!remembered) return null
  return (
    devices.find((device) => device.id === remembered.id) ??
    (remembered.label ? devices.find((device) => device.label === remembered.label) : undefined) ??
    null
  )
}

/** Chromium lists the system choice as an extra "default" device; WebKit does not. */
function split(all: MediaDeviceInfo[], kind: MediaDeviceKind): { devices: AudioDevice[]; defaultLabel: string } {
  const ofKind = all.filter((device) => device.kind === kind)
  const pseudo = ofKind.find((device) => device.deviceId === "default")
  const devices = ofKind
    .filter((device) => device.deviceId && device.deviceId !== "default" && device.deviceId !== "communications")
    .map((device, index) => ({
      id: device.deviceId,
      label: device.label || `${kind === "audioinput" ? "Microphone" : "Output"} ${index + 1}`,
    }))
  return { devices, defaultLabel: pseudo?.label.replace(/^Default - /, "") ?? "" }
}

/** Follow a remembered device whose id changed, so the next lookup is direct. */
function adopt(key: string, chosen: AudioDevice | null, present: AudioDevice | null): AudioDevice | null {
  if (!chosen || !present || present.id === chosen.id) return chosen
  remember(key, present)
  return present
}

let listening = false

/** Re-read the connected devices. Names appear only once the mic has been opened. */
export async function listDevices(): Promise<void> {
  if (!navigator.mediaDevices?.enumerateDevices) return
  if (!listening) {
    navigator.mediaDevices.addEventListener("devicechange", () => void listDevices())
    listening = true
  }
  const all = await navigator.mediaDevices.enumerateDevices()
  const inputs = split(all, "audioinput")
  const outputs = split(all, "audiooutput")
  audioDevices.namesKnown = all.some((device) => device.kind === "audioinput" && device.label !== "")
  if (!audioDevices.namesKnown) return
  audioDevices.inputs = inputs.devices
  audioDevices.outputs = outputs.devices
  if (inputs.defaultLabel) audioDevices.defaultInputLabel = inputs.defaultLabel
  audioDevices.defaultOutputLabel = outputs.defaultLabel
  audioDevices.chosenInput = adopt(INPUT_KEY, audioDevices.chosenInput, resolve(audioDevices.chosenInput, inputs.devices))
  audioDevices.chosenOutput = adopt(OUTPUT_KEY, audioDevices.chosenOutput, resolve(audioDevices.chosenOutput, outputs.devices))
  syncSinks()
}

function isGone(reason: unknown): boolean {
  return reason instanceof DOMException && (reason.name === "OverconstrainedError" || reason.name === "NotFoundError")
}

function noteInUse(stream: MediaStream): void {
  const label = stream.getAudioTracks()[0]?.label ?? ""
  audioDevices.inputInUse = label
  // With nothing chosen, the opened track is the most reliable name for the
  // system default: WebKit offers no other.
  if (label && !audioDevices.chosenInput) audioDevices.defaultInputLabel = label
}

/**
 * Open the chosen microphone, or the system default when nothing is chosen
 * or the chosen one is not connected (then `notice` says so).
 */
export async function openMicrophone(base: MediaTrackConstraints): Promise<MediaStream> {
  const chosen = audioDevices.chosenInput
  if (chosen) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: chosen.id } } })
      audioDevices.notice = ""
      noteInUse(stream)
      void listDevices().catch(() => undefined)
      return stream
    } catch (reason) {
      if (!isGone(reason)) throw reason
    }
  }
  let stream = await navigator.mediaDevices.getUserMedia({ audio: base })
  // The microphone is open now, so device names are visible: look for the
  // chosen device by name, in case only its id changed.
  await listDevices().catch(() => undefined)
  const present = resolve(chosen, audioDevices.inputs)
  if (chosen && present && present.id !== stream.getAudioTracks()[0]?.getSettings().deviceId) {
    stream.getTracks().forEach((track) => track.stop())
    stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: present.id } } })
  }
  noteInUse(stream)
  audioDevices.notice = chosen && !present
    ? `${chosen.label} is not connected, so ${audioDevices.inputInUse || "the system default"} is being used.`
    : ""
  return stream
}

export function chooseInput(id: string): void {
  const device = audioDevices.inputs.find((each) => each.id === id) ?? null
  audioDevices.chosenInput = device
  audioDevices.notice = ""
  remember(INPUT_KEY, device)
}

export function chooseOutput(id: string): void {
  const device = audioDevices.outputs.find((each) => each.id === id) ?? null
  audioDevices.chosenOutput = device
  remember(OUTPUT_KEY, device)
  syncSinks()
}

// --- Output routing --------------------------------------------------------

type SinkTarget = HTMLMediaElement & { setSinkId?: (id: string) => Promise<void> }

const routed = new Set<SinkTarget>()
/** Output switches in flight, so playback can wait for them. */
const pending = new Set<Promise<void>>()
/** The sink each element is known to be on; absent means the system default. */
const applied = new WeakMap<SinkTarget, string>()

function wantedSink(): string {
  const chosen = audioDevices.chosenOutput
  if (!chosen || !canChooseOutput) return ""
  return resolve(chosen, audioDevices.outputs)?.id ?? chosen.id
}

/**
 * Move every routed element to the chosen output. Elements already there are
 * left alone, and an element on the system default is never "moved" to it:
 * WebKit rejects every call made outside a user gesture, so only calls that
 * change something are worth making.
 */
function syncSinks(): void {
  const wanted = wantedSink()
  routed.forEach((element) => {
    if ((applied.get(element) ?? "") === wanted || !element.setSinkId) return
    const switching = element.setSinkId(wanted).then(
      () => {
        applied.set(element, wanted)
        audioDevices.outputNotice = ""
      },
      (reason: unknown) => {
        // Without a gesture WebKit refuses; the next click retries. Any other
        // refusal means the device cannot be used: say so, don't hide it.
        if (reason instanceof DOMException && reason.name === "NotAllowedError") return
        const label = audioDevices.chosenOutput?.label ?? "The chosen output"
        audioDevices.outputNotice = `${label} could not be used, so sound is playing on the system output.`
      },
    )
    pending.add(switching)
    void switching.finally(() => pending.delete(switching))
  })
}

/** Resolves once every output switch in flight has finished (or failed). */
export async function outputsSettled(): Promise<void> {
  syncSinks()
  await Promise.allSettled([...pending])
}

/** Route an element right now; call it from a click, before playing. */
export async function routeNow(element: HTMLMediaElement): Promise<void> {
  const target = element as SinkTarget
  const wanted = wantedSink()
  if ((applied.get(target) ?? "") === wanted || !target.setSinkId) return
  try {
    await target.setSinkId(wanted)
    applied.set(target, wanted)
  } catch {
    // Plays on the system default instead, which beats silence.
  }
}

if (typeof document !== "undefined" && canChooseOutput) {
  // WebKit only honours setSinkId inside a user gesture. The press that
  // starts playback is one, and arrives before the click that calls play().
  document.addEventListener("pointerdown", syncSinks, { capture: true })
  document.addEventListener("keydown", syncSinks, { capture: true })
}

/** `v-audio-output` keeps an <audio> element on the chosen output. */
export const vAudioOutput: Directive<HTMLMediaElement> = {
  mounted(element) {
    routed.add(element)
    syncSinks()
  },
  unmounted(element) {
    routed.delete(element)
  },
}

/**
 * Where a Web Audio graph should connect to reach the chosen output.
 *
 * Chromium can route an AudioContext directly. WebKit cannot, so the audio
 * goes through a stream into an <audio> element, which can be routed.
 */
export function contextOutput(context: AudioContext): AudioNode {
  const wanted = wantedSink()
  if (!wanted) return context.destination
  const routable = context as AudioContext & { setSinkId?: (id: string) => Promise<void> }
  if (routable.setSinkId) {
    void routable.setSinkId(wanted).catch(() => undefined)
    return context.destination
  }
  const stream = context.createMediaStreamDestination()
  const element = new Audio() as SinkTarget
  element.srcObject = stream.stream
  routed.add(element)
  void routeNow(element).then(() => element.play()).catch(() => undefined)
  context.addEventListener("statechange", () => {
    if (context.state !== "closed") return
    element.pause()
    element.srcObject = null
    routed.delete(element)
  })
  return stream
}
