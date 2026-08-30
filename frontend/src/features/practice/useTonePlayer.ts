import { onBeforeUnmount, ref } from "vue"

export interface ToneStep {
  midi: number
  seconds: number
}

export function midiToHertz(midi: number, concertPitchHertz = 440): number {
  return concertPitchHertz * Math.pow(2, (midi - 69) / 12)
}

/**
 * Plays reference pitches for the practice exercises.
 *
 * A triangle wave rather than a sine: a pure sine is surprisingly hard to
 * match by ear, because there are no harmonics to lock onto. The short
 * attack and release exist to avoid the click a hard gate produces, which is
 * loud on headphones and easy to mistake for part of the note.
 */
export function useTonePlayer() {
  const playing = ref(false)
  let context: AudioContext | null = null
  let stopAt = 0

  function ensureContext(): AudioContext {
    if (!context) context = new AudioContext()
    return context
  }

  function stop(): void {
    playing.value = false
    stopAt = 0
    if (context) {
      void context.close()
      context = null
    }
  }

  async function playSequence(steps: ToneStep[], gapSeconds = 0.12): Promise<void> {
    stop()
    if (steps.length === 0) return
    const audio = ensureContext()
    if (audio.state === "suspended") await audio.resume()

    let cursor = audio.currentTime + 0.05
    for (const step of steps) {
      const oscillator = audio.createOscillator()
      const gain = audio.createGain()
      oscillator.type = "triangle"
      oscillator.frequency.value = midiToHertz(step.midi)
      const attack = 0.02
      const release = 0.08
      gain.gain.setValueAtTime(0, cursor)
      gain.gain.linearRampToValueAtTime(0.22, cursor + attack)
      gain.gain.setValueAtTime(0.22, cursor + step.seconds - release)
      gain.gain.linearRampToValueAtTime(0, cursor + step.seconds)
      oscillator.connect(gain)
      gain.connect(audio.destination)
      oscillator.start(cursor)
      oscillator.stop(cursor + step.seconds)
      cursor += step.seconds + gapSeconds
    }

    playing.value = true
    stopAt = cursor
    const remaining = (stopAt - audio.currentTime) * 1000
    window.setTimeout(() => {
      // A later sequence may have started in the meantime; only the one that
      // set this deadline should clear the flag.
      if (playing.value && stopAt <= (context?.currentTime ?? Infinity) + 0.05) stop()
      else playing.value = false
    }, Math.max(0, remaining))
  }

  function playNote(midi: number, seconds: number): Promise<void> {
    return playSequence([{ midi, seconds }])
  }

  onBeforeUnmount(stop)

  return { playing, playNote, playSequence, stop }
}
