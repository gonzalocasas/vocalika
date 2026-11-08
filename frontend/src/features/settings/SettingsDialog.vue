<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiJson } from "../../shared/api"
import AboutPanel from "../about/AboutPanel.vue"
import AudioSettings from "./AudioSettings.vue"
import type { FolderInspection, StorageStatus } from "../../shared/types"
import { storageAction } from "./storageChoice"

// "setup" is the first start: a folder has to be chosen before anything else,
// so the dialog cannot be dismissed.
const props = defineProps<{ mode: "setup" | "settings" }>()
const tab = ref<"storage" | "audio" | "about">("storage")
const TITLES = { storage: "Storage", audio: "Audio devices", about: "About Vocalika" } as const
const emit = defineEmits<{ changed: [status: StorageStatus]; close: [] }>()

const status = ref<StorageStatus | null>(null)
const draft = ref("")
const inspection = ref<FolderInspection | null>(null)
const inspectionError = ref("")
const moveProjects = ref(true)
const saving = ref(false)
const browsing = ref(false)
const error = ref("")
let inspectTimer: number | undefined
let inspectRequest = 0

const action = computed(() =>
  status.value && inspection.value
    ? storageAction(status.value, inspection.value, moveProjects.value)
    : null,
)
const problem = computed(() => inspectionError.value || inspection.value?.problem || "")

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`
}

async function loadStatus(): Promise<void> {
  try {
    status.value = await apiJson<StorageStatus>("/api/settings/storage")
    draft.value = props.mode === "setup" ? status.value.suggested_directory : status.value.data_directory
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function inspect(path: string): Promise<void> {
  const request = ++inspectRequest
  try {
    const result = await apiJson<FolderInspection>("/api/settings/storage/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    })
    if (request !== inspectRequest) return
    inspection.value = result
    inspectionError.value = ""
    // A folder that already holds a library is usually one being reconnected
    // (another drive, a restored backup): switching is the expected choice.
    moveProjects.value = result.project_count === 0
  } catch (reason) {
    if (request !== inspectRequest) return
    inspection.value = null
    inspectionError.value = reason instanceof Error ? reason.message : String(reason)
  }
}

watch(draft, (path) => {
  if (inspectTimer !== undefined) window.clearTimeout(inspectTimer)
  inspection.value = null
  inspectionError.value = ""
  if (!path.trim()) return
  inspectTimer = window.setTimeout(() => void inspect(path), 250)
})

async function browse(): Promise<void> {
  browsing.value = true
  error.value = ""
  try {
    const result = await apiJson<{ path: string | null }>("/api/settings/storage/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: draft.value }),
    })
    if (result.path) draft.value = result.path
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    browsing.value = false
  }
}

async function confirm(): Promise<void> {
  if (!action.value?.allowed || !inspection.value) return
  saving.value = true
  error.value = ""
  try {
    const result = await apiJson<StorageStatus>("/api/settings/storage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: inspection.value.path, move: action.value.move }),
    })
    status.value = result
    emit("changed", result)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    saving.value = false
  }
}

function requestClose(): void {
  if (props.mode === "settings" && !saving.value) emit("close")
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") requestClose()
}

onMounted(() => {
  void loadStatus()
  window.addEventListener("keydown", onKeydown)
  document.body.classList.add("modal-open")
})
onBeforeUnmount(() => {
  if (inspectTimer !== undefined) window.clearTimeout(inspectTimer)
  window.removeEventListener("keydown", onKeydown)
  document.body.classList.remove("modal-open")
})
</script>

<template>
  <div class="settings-overlay" @click.self="requestClose">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <header class="settings-header">
        <div>
          <span class="settings-kicker">{{ mode === "setup" ? "WELCOME" : "SETTINGS" }}</span>
          <h3 id="settings-title">
            {{ mode === "setup" ? "Where should Vocalika keep your songs?" : TITLES[tab] }}
          </h3>
        </div>
        <button v-if="mode === 'settings'" class="tool-button close" aria-label="Close settings" :disabled="saving" @click="requestClose">✕</button>
      </header>

      <nav v-if="mode === 'settings'" class="settings-tabs" role="tablist" aria-label="Settings sections">
        <button
          v-for="option in (['storage', 'audio', 'about'] as const)"
          :key="option"
          role="tab"
          :aria-selected="tab === option"
          :class="{ active: tab === option }"
          :disabled="saving"
          @click="tab = option"
        >{{ option.toUpperCase() }}</button>
      </nav>

      <div v-if="tab === 'audio'" class="settings-body">
        <AudioSettings />
      </div>
      <div v-else-if="tab === 'about'" class="settings-body">
        <AboutPanel />
      </div>
      <footer v-if="tab === 'audio' || tab === 'about'" class="settings-footer">
        <button class="ghost-button accent-button" @click="requestClose">DONE</button>
      </footer>

      <template v-else>
      <div class="settings-body">
        <p v-if="mode === 'setup'" class="settings-lede">
          Every song you add and every take you record is saved in one folder on this computer.
          Pick somewhere you will find again, and that is backed up. You can move it later in Settings.
        </p>

        <div v-if="status && mode === 'settings'" class="storage-current">
          <span>CURRENT FOLDER</span>
          <code>{{ status.data_directory }}</code>
          <small>{{ plural(status.project_count, "project") }}</small>
        </div>

        <label class="storage-field">
          <span>{{ mode === "setup" ? "FOLDER" : "NEW FOLDER" }}</span>
          <div class="storage-input-row">
            <input
              v-model="draft"
              class="graphite-input"
              type="text"
              spellcheck="false"
              autocomplete="off"
              placeholder="~/Music/Vocalika"
              :disabled="saving"
            />
            <button
              v-if="status?.can_browse"
              type="button"
              class="ghost-button compact"
              :disabled="saving || browsing"
              @click="browse"
            >{{ browsing ? "CHOOSING…" : "BROWSE…" }}</button>
          </div>
        </label>

        <p v-if="problem" class="inline-error">{{ problem }}</p>
        <p v-else-if="action" class="storage-note">{{ action.note }}</p>

        <div v-if="action?.offersMove" class="storage-choice" role="radiogroup" aria-label="What to do with your projects">
          <label class="check-row">
            <input v-model="moveProjects" type="radio" :value="true" :disabled="saving" />
            <span><b>Move my {{ plural(status?.project_count ?? 0, "project") }} there</b><br />They leave the current folder.</span>
          </label>
          <label class="check-row">
            <input v-model="moveProjects" type="radio" :value="false" :disabled="saving" />
            <span><b>Only switch folders</b><br />Projects in the current folder stay there, and stop showing up until you switch back.</span>
          </label>
        </div>

        <p v-if="error" class="inline-error">{{ error }}</p>
      </div>

      <footer class="settings-footer">
        <span v-if="saving && action?.move" class="storage-note">Moving your projects. Keep Vocalika open until this finishes.</span>
        <button v-if="mode === 'settings'" class="text-button" :disabled="saving" @click="requestClose">CANCEL</button>
        <button class="ghost-button accent-button" :disabled="!action?.allowed || saving" @click="confirm">
          {{ saving ? (action?.move ? "MOVING…" : "SAVING…") : action?.label ?? "USE THIS FOLDER" }}
        </button>
      </footer>
      </template>
    </section>
  </div>
</template>
