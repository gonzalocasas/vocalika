<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"

import { installUpdate, watchForUpdate, type UpdateNotice } from "./desktopUpdate"

const notice = ref<UpdateNotice | null>(null)
const dismissed = ref(false)
const installing = ref(false)
const failed = ref("")
let stop: () => void = () => {}

onMounted(async () => {
  stop = await watchForUpdate((ready) => {
    notice.value = ready
  })
})
onBeforeUnmount(() => stop())

async function restart(): Promise<void> {
  installing.value = true
  failed.value = ""
  try {
    await installUpdate()
  } catch (error) {
    installing.value = false
    failed.value = String(error)
  }
}
</script>

<template>
  <div v-if="notice && !dismissed" class="update-notice" role="status">
    <span>
      VOCALIKA {{ notice.version }} IS READY
      <template v-if="failed"> · <b :title="failed">COULD NOT INSTALL</b></template>
    </span>
    <button type="button" class="update-restart" :disabled="installing" @click="restart">
      {{ installing ? "RESTARTING…" : "RESTART TO UPDATE" }}
    </button>
    <button
      type="button"
      class="update-later"
      title="Later: it installs when you quit Vocalika"
      aria-label="Later: it installs when you quit Vocalika"
      :disabled="installing"
      @click="dismissed = true"
    >LATER</button>
  </div>
</template>
