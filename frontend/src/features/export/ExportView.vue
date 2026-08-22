<script setup lang="ts">
import type { Project, Take } from "../../shared/types"

defineProps<{ project: Project; take: Take | null }>()
</script>

<template>
  <section class="feature-panel export-boundary">
    <p class="mono-eyebrow accent-text">EXPORT / NEXT PROCESSING MODULE</p>
    <h2>Your vocal over the reference instrumental</h2>
    <p>
      The project already owns the instrumental stem and take source required for mixdown.
      Rendering and preview are intentionally isolated from recording and comparison, and will be
      enabled without changing either feature.
    </p>
    <div class="export-readiness">
      <span>INSTRUMENTAL <b>{{ project.reference.instrumental_path ? "READY" : "UNAVAILABLE" }}</b></span>
      <span>SELECTED TAKE <b>{{ take?.name || "NONE" }}</b></span>
    </div>
  </section>
</template>
