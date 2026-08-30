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
  pending.value = { kind: "sustained", target: exercise.midi }
  // Hear it first, then record: matching a pitch from memory is a different
  // and much harder skill than matching one you have just been given.
  await tone.playNote(exercise.midi, 1.4)
  window.setTimeout(() => void attempt.record(exercise.id, exercise.hold_seconds), 1600)
}

async function tryInterval(exercise: IntervalExercise): Promise<void> {
  pending.value = { kind: "interval", target: exercise.from_midi, to: exercise.to_midi }
  await tone.playSequence([{ midi: exercise.from_midi, seconds: 1.0 }])
  window.setTimeout(() => void attempt.record(exercise.id, 2.6), 1200)
}

async function tryWarmupStep(midi: number, index: number): Promise<void> {
  pending.value = { kind: "warmup", target: midi }
  await tone.playNote(midi, 1.2)
  window.setTimeout(() => void attempt.record(`warmup-${index}`, 2.0), 1400)
}

const verdictClass = (verdict: string) => `verdict-${verdict}`

function centsLabel(cents: number | null): string {
  if (cents === null) return "—"
  const rounded = Math.round(cents)
  if (rounded === 0) return "exactly on pitch"
  return `${Math.abs(rounded)}¢ ${rounded < 0 ? "flat" : "sharp"}`
}

const currentScore = computed<AttemptScore | null>(() => attempt.score.value)
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
      <div v-if="attempt.recorder.state.value === 'recording'" class="practice-live">
        ● LISTENING — sing now
        <button class="ghost-button compact" @click="attempt.finish">DONE</button>
      </div>
      <p v-else-if="attempt.scoring.value" class="feature-note">Measuring that attempt…</p>

      <div v-if="currentScore" class="attempt-score" :class="verdictClass(currentScore.verdict)">
        <template v-if="isIntervalScore(currentScore)">
          <strong>{{ VERDICT_LABEL[currentScore.verdict] ?? currentScore.verdict }}</strong>
          <span v-if="currentScore.interval_error_cents !== null">
            You sang {{ currentScore.sung_semitones?.toFixed(1) }} semitones,
            the leap is {{ currentScore.target_semitones }} —
            {{ centsLabel(currentScore.interval_error_cents) }}
          </span>
          <small v-if="currentScore.first">
            Starting note {{ centsLabel(currentScore.first.centre_cents) }} ·
            landing note {{ centsLabel(currentScore.second?.centre_cents ?? null) }}
          </small>
        </template>
        <template v-else>
          <strong>{{ VERDICT_LABEL[currentScore.verdict] ?? currentScore.verdict }}</strong>
          <span>
            Target {{ currentScore.target_note }} ·
            you sang {{ currentScore.sung_note ?? "—" }} ·
            {{ centsLabel(currentScore.centre_cents) }}
          </span>
          <small v-if="currentScore.steadiness_cents !== null">
            Held {{ currentScore.held_seconds.toFixed(1) }}s ·
            wandered ±{{ Math.round(currentScore.steadiness_cents) }}¢ around your own centre
          </small>
        </template>
        <button class="text-button" @click="attempt.reset">CLEAR</button>
      </div>

      <section v-if="plan.warmup" class="feature-panel practice-panel">
        <p class="mono-eyebrow accent-text">01 · WARM UP THE RANGE</p>
        <h3>Walk from the middle to the edges</h3>
        <p class="feature-note">
          Built outward from the comfortable middle rather than upward from the
          bottom, so the voice is warm before it reaches the extremes.
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
        <p class="feature-note">
          Widest first — these are the ones that go wrong. Your starting note is
          played, then you sing both.
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
    </template>
  </section>
</template>
