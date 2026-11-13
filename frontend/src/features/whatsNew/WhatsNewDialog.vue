<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue"

import type { Release } from "./changelog"

defineProps<{
  version: string
  releases: Release[]
  /** No latency measured yet: the takes will not line up, so say so here. */
  needsLatency: boolean
}>()
const emit = defineEmits<{ close: []; measure: []; tour: [] }>()

function formatDate(date: string): string {
  const parsed = new Date(`${date}T12:00:00`)
  return Number.isNaN(parsed.getTime())
    ? date
    : new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(parsed)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") emit("close")
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown)
  document.body.classList.add("modal-open")
})
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown)
  document.body.classList.remove("modal-open")
})
</script>

<template>
  <div class="settings-overlay" @click.self="emit('close')">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="whats-new-title">
      <header class="settings-header">
        <div>
          <span class="settings-kicker">VERSION {{ version }}</span>
          <h3 id="whats-new-title">What's new in Vocalika</h3>
        </div>
        <button class="tool-button close" aria-label="Close" @click="emit('close')">✕</button>
      </header>

      <div class="settings-body">
        <section v-if="needsLatency" class="latency-nudge">
          <div>
            <b>Your latency has not been measured yet.</b>
            Until it is, your takes may sit a little late against the song. It takes a few seconds.
          </div>
          <button class="ghost-button compact accent-button" @click="emit('measure')">MEASURE NOW</button>
        </section>

        <article v-for="release in releases" :key="release.version" class="release-notes">
          <h4>{{ release.version }} <small v-if="release.date">{{ formatDate(release.date) }}</small></h4>
          <template v-if="release.features.length">
            <span class="settings-kicker">NEW</span>
            <ul><li v-for="entry in release.features" :key="entry">{{ entry }}</li></ul>
          </template>
          <template v-if="release.fixes.length">
            <span class="settings-kicker">FIXED</span>
            <ul><li v-for="entry in release.fixes" :key="entry">{{ entry }}</li></ul>
          </template>
        </article>
      </div>

      <footer class="settings-footer">
        <button class="text-button" @click="emit('tour')">TAKE THE TOUR</button>
        <button class="ghost-button accent-button" @click="emit('close')">GOT IT</button>
      </footer>
    </section>
  </div>
</template>
