<script setup lang="ts">
defineProps<{ amplitudes: number[]; active?: boolean }>()
</script>

<template>
  <div class="waveform-bars" :class="{ active }" aria-hidden="true">
    <i
      v-for="(amplitude, index) in amplitudes"
      :key="index"
      :style="{ height: `${Math.max(4, amplitude * 100)}%` }"
    ></i>
  </div>
</template>
