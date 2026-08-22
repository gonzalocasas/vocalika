<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiJson } from "../../shared/api"
import type { WaveformEnvelope } from "../../shared/types"
import WaveformBars from "../../shared/WaveformBars.vue"

const props = defineProps<{ projectId: string }>()
const amplitudes = ref<number[]>([])

onMounted(async () => {
  try {
    const payload = await apiJson<WaveformEnvelope>(`/api/projects/${props.projectId}/waveform/mix`)
    const stride = Math.max(1, Math.floor(payload.amplitude.length / 34))
    amplitudes.value = payload.amplitude.filter((_, index) => index % stride === 0).slice(0, 34)
  } catch {
    amplitudes.value = []
  }
})
</script>

<template>
  <WaveformBars :amplitudes="amplitudes" />
</template>
