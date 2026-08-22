<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiJson } from "../../shared/api"
import type { WaveformEnvelope } from "../../shared/types"
import WaveformBars from "../../shared/WaveformBars.vue"

const props = defineProps<{ projectId: string; takeId: string; active?: boolean }>()
const amplitudes = ref<number[]>([])
onMounted(async () => {
  try {
    const payload = await apiJson<WaveformEnvelope>(
      `/api/projects/${props.projectId}/takes/${props.takeId}/waveform`,
    )
    amplitudes.value = payload.amplitude
  } catch {
    amplitudes.value = []
  }
})
</script>

<template><WaveformBars :amplitudes="amplitudes" :active="active" /></template>
