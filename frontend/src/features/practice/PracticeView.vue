<script setup lang="ts">
import { computed, ref, watch } from "vue"

import { apiJson } from "../../shared/api"
import type { Project } from "../../shared/types"
import {
  isIntervalScore,
  VERDICT_LABEL,
  type AttemptScore,
  type IntervalExercise,
  type PracticePlan,
  type SustainedExercise,
} from "./types"
import { centsLabel, leapLabel, leapSpanLabel } from "./labels"
import { useAttempt } from "./useAttempt"
import { useTonePlayer } from "./useTonePlayer"

const props = defineProps<{ project: Project }>()

const plan = ref<PracticePlan | null>(null)
const loading = ref(true)
const loadError = ref("")
const tone = useTonePlayer()
const attempt = useAttempt(props.project.id)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ""
  plan.value = null
  try {
    plan.value = await apiJson<PracticePlan>(
      `/api/projects/${props.project.id}/practice?transpose=${props.project.transpose_semitones}`,
    )
    const wanted = [
      ...(plan.value.warmup?.steps_midi ?? []),
      ...plan.value.sustained.map((exercise) => exercise.midi),
      ...plan.value.intervals.flatMap((exercise) => [exercise.from_midi, exercise.to_midi]),
    ]
    void tone.preload(wanted)
  } catch (reason) {
    loadError.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loading.value = false
  }
}

watch(() => [props.project.id, props.project.transpose_semitones], load, { immediate: true })

// The recorder finishes asynchronously; submit as soon as the file exists.
watch(attempt.recorder.recordedFile, (file) => {
  if (!file || !pending.value) return
  const { kind, target, to } = pending.value
  void attempt.submit(kind, target, to)
})

const pending = ref<{
  kind: "sustained" | "interval" | "warmup"
  target: number
  to?: number
  prompt: string
  seconds: number
} | null>(null)

function hearSustained(exercise: SustainedExercise): void {
  void tone.playNote(exercise.midi, Math.min(3, exercise.hold_seconds))
}

function hearInterval(exercise: IntervalExercise): void {
  void tone.playSequence([
    { midi: exercise.from_midi, seconds: 1.1 },
    { midi: exercise.to_midi, seconds: 1.4 },
  ])
}

function hearWarmup(): void {
  const steps = plan.value?.warmup?.steps_midi ?? []
  void tone.playSequence(steps.map((midi) => ({ midi, seconds: 0.9 })), 0.1)
}

async function trySustained(exercise: SustainedExercise): Promise<void> {
  pending.value = {
    kind: "sustained",
    target: exercise.midi,
    prompt: `Hold ${exercise.note}`,
    seconds: exercise.hold_seconds,
  }
  // Hear it first, then record: matching a pitch from memory is a different
  // and much harder skill than matching one you have just been given.
  await tone.playNote(exercise.midi, 1.4)
  window.setTimeout(() => void attempt.record(exercise.id, exercise.hold_seconds), 1600)
}

async function tryInterval(exercise: IntervalExercise): Promise<void> {
  pending.value = {
    kind: "interval",
    target: exercise.from_midi,
    to: exercise.to_midi,
    // Say both halves explicitly: the leap is the exercise, and it is not
    // obvious from a card that both notes are meant to be sung.
    prompt: `Sing ${exercise.from_note}, then leap ${exercise.direction} to ${exercise.to_note}`,
    seconds: 2.6,
  }
  await tone.playSequence([{ midi: exercise.from_midi, seconds: 1.0 }])
  window.setTimeout(() => void attempt.record(exercise.id, 2.6), 1200)
}

async function tryWarmupStep(midi: number, index: number): Promise<void> {
  pending.value = {
    kind: "warmup",
    target: midi,
    prompt: `Hold ${plan.value?.warmup?.steps_note[index] ?? ""}`,
    seconds: 2.0,
  }
  await tone.playNote(midi, 1.2)
  window.setTimeout(() => void attempt.record(`warmup-${index}`, 2.0), 1400)
}

const verdictClass = (verdict: string) => `verdict-${verdict}`

const currentScore = computed<AttemptScore | null>(() => attempt.score.value)

const dockVisible = computed(
  () =>
    attempt.recorder.state.value === "recording"
    || attempt.scoring.value
    || currentScore.value !== null,
)
const dockClass = computed(() =>
  attempt.recorder.state.value === "recording"
    ? "listening"
    : currentScore.value
      ? verdictClass(currentScore.value.verdict)
      : "",
)
const countdown = computed(() => {
  const total = pending.value?.seconds ?? 0
  const left = Math.max(0, total + 0.6 - attempt.recorder.elapsedSeconds.value)
  return `${left.toFixed(1)}s`
})
</script>

<template>
  <section class="practice-view">
    <div class="compare-heading">
      <div>
        <p class="mono-eyebrow accent-text">PREPARE</p>
        <h2>Warm up for this song</h2>
      </div>
      <p v-if="plan?.range" class="practice-range">
        {{ plan.range.low_note }}–{{ plan.range.high_note }}
        <small>{{ plan.note_count }} notes</small>
      </p>
    </div>

    <p v-if="loading" class="feature-note">Reading the reference…</p>
    <p v-else-if="loadError" class="inline-error">{{ loadError }}</p>

    <template v-else-if="plan">
      <p v-if="attempt.error.value" class="inline-error">{{ attempt.error.value }}</p>

      <section v-if="plan.warmup" class="feature-panel practice-panel">
        <p class="mono-eyebrow accent-text">01 · WARM UP THE RANGE</p>
        <h3>Walk from the middle to the edges</h3>
        <p class="feature-note">
          Built outward from the comfortable middle rather than upward from the
          bottom, so the voice is warm before it reaches the extremes. Tap a
          note to hear it and sing it back.
        </p>
        <div class="warmup-ladder">
          <button
            v-for="(note, index) in plan.warmup.steps_note"
            :key="note"
            class="ladder-step"
            :class="{ active: attempt.activeId.value === `warmup-${index}` }"
            @click="tryWarmupStep(plan.warmup.steps_midi[index], index)"
          >{{ note }}</button>
        </div>
        <button class="ghost-button compact" @click="hearWarmup">▶ HEAR THE LADDER</button>
      </section>

      <section v-if="plan.sustained.length" class="feature-panel practice-panel">
        <p class="mono-eyebrow accent-text">02 · HOLD THE LONG NOTES</p>
        <h3>The notes this song asks you to sustain</h3>
        <p class="feature-note">
          <b>TRY</b> plays the note, then listens. Sing it back and hold it
          steady for the whole count — the start and end are trimmed off, so
          easing into the note costs you nothing.
        </p>
        <div class="exercise-grid">
          <article
            v-for="exercise in plan.sustained"
            :key="exercise.id"
            :class="{ active: attempt.activeId.value === exercise.id }"
          >
            <b>{{ exercise.note }}</b>
            <span>hold {{ exercise.hold_seconds.toFixed(1) }}s</span>
            <div>
              <button class="ghost-button compact" @click="hearSustained(exercise)">▶ HEAR</button>
              <button class="solid-button compact" @click="trySustained(exercise)">● TRY</button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="plan.intervals.length" class="feature-panel practice-panel">
        <p class="mono-eyebrow accent-text">03 · THE LEAPS IN THIS SONG</p>
        <h3>Commit to the distance</h3>
        <ol class="how-to">
          <li><b>HEAR</b> plays the two notes so you know the leap.</li>
          <li><b>TRY</b> plays only the <em>first</em> note.</li>
          <li>
            Sing that first note, hold it a moment, then jump straight to the
            second. Sing them both, back to back, in one breath — no sliding
            between them.
          </li>
        </ol>
        <p class="feature-note">
          Widest leaps first: those are the ones that go wrong. The jump is
          scored separately from the two notes, so landing the leap while
          sitting a little low still counts as a good leap.
        </p>
        <div class="exercise-grid">
          <article
            v-for="exercise in plan.intervals"
            :key="exercise.id"
            :class="{ active: attempt.activeId.value === exercise.id }"
          >
            <b>{{ exercise.from_note }} → {{ exercise.to_note }}</b>
            <span>{{ exercise.name }} {{ exercise.direction }} · {{ exercise.occurrences }}× in song</span>
            <div>
              <button class="ghost-button compact" @click="hearInterval(exercise)">▶ HEAR</button>
              <button class="solid-button compact" @click="tryInterval(exercise)">● TRY</button>
            </div>
          </article>
        </div>
      </section>
      <p class="sample-credit">
        Reference notes played on the
        <a href="https://archive.org/details/SalamanderGrandPianoV3" target="_blank" rel="noopener">
          Salamander Grand Piano</a>
        by Alexander Holm, licensed
        <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noopener">CC-BY 3.0</a>.
        <span v-if="!tone.usingSamples.value">Samples unavailable — using a synthesised tone.</span>
      </p>
    </template>

    <!-- Fixed, because the exercise being worked on may be far down the page
         and feedback that has scrolled out of view is feedback nobody reads. -->
    <div v-if="dockVisible" class="practice-dock" :class="dockClass">
      <template v-if="attempt.recorder.state.value === 'recording'">
        <div class="dock-main">
          <span class="dock-pulse"></span>
          <strong>{{ pending?.prompt ?? "Sing now" }}</strong>
        </div>
        <span class="dock-meta">{{ countdown }}</span>
        <button class="ghost-button compact" @click="attempt.finish">DONE</button>
      </template>

      <template v-else-if="attempt.scoring.value">
        <div class="dock-main"><strong>Measuring…</strong></div>
      </template>

      <template v-else-if="currentScore">
        <div class="dock-main">
          <strong>{{ VERDICT_LABEL[currentScore.verdict] ?? currentScore.verdict }}</strong>
          <template v-if="isIntervalScore(currentScore)">
            <span v-if="currentScore.interval_error_cents !== null">
              The leap should span {{ leapSpanLabel(currentScore.target_semitones) }};
              you sang {{ Math.abs(currentScore.sung_semitones ?? 0).toFixed(1) }} —
              {{ leapLabel(currentScore) }}
            </span>
            <small v-if="currentScore.first">
              You started {{ centsLabel(currentScore.first.centre_cents) }} and landed
              {{ centsLabel(currentScore.second?.centre_cents ?? null) }}
            </small>
          </template>
          <template v-else>
            <span>
              target {{ currentScore.target_note }} · you sang
              {{ currentScore.sung_note ?? "—" }} · {{ centsLabel(currentScore.centre_cents) }}
            </span>
            <small v-if="currentScore.steadiness_cents !== null">
              held {{ currentScore.held_seconds.toFixed(1) }}s · wandered
              ±{{ Math.round(currentScore.steadiness_cents) }}¢ around your own centre
            </small>
          </template>
        </div>
        <button class="text-button" @click="attempt.reset">DISMISS</button>
      </template>
    </div>
  </section>
</template>
