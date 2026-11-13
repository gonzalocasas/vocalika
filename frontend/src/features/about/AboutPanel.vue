<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { apiJson } from "../../shared/api"
import { openExternal } from "../../shared/externalLink"
import { GIANTS, MODELS_AND_MEDIA } from "./credits"

interface Package {
  name: string
  version: string
  license: string
  url: string | null
}

interface LicenseText {
  file: string
  text: string
}

interface About {
  version: string
  desktop: boolean
  platform: string
  python_packages: Package[]
  launcher_packages: Package[] | null
}

interface Group {
  id: "python" | "web" | "launcher"
  title: string
  what: string
  packages: Package[]
}

const emit = defineEmits<{ whatsNew: []; tour: [] }>()
const about = ref<About | null>(null)
const webPackages = ref<(Package & { licenses: LicenseText[] })[]>([])
const error = ref("")
const filter = ref("")
const texts = ref<Record<string, LicenseText[] | "loading" | string>>({})

onMounted(async () => {
  try {
    about.value = await apiJson<About>("/api/about")
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
  try {
    // Written by the frontend build; absent from a development server.
    const response = await fetch("/third-party.json")
    if (response.ok) webPackages.value = (await response.json()).packages
  } catch {
    webPackages.value = []
  }
})

const groups = computed<Group[]>(() => {
  if (!about.value) return []
  const all: Group[] = [
    {
      id: "python",
      title: "Analysis and server",
      what: "Python packages, installed from PyPI on first start",
      packages: about.value.python_packages,
    },
    { id: "web", title: "The app's interface", what: "JavaScript bundled into the page", packages: webPackages.value },
  ]
  if (about.value.launcher_packages) {
    all.push({
      id: "launcher",
      title: "Desktop launcher",
      what: "Rust crates compiled into the app, and the bundled uv",
      packages: about.value.launcher_packages,
    })
  }
  return all
})

const query = computed(() => filter.value.trim().toLowerCase())
function visible(group: Group): Package[] {
  if (!query.value) return group.packages
  return group.packages.filter((item) => `${item.name} ${item.license}`.toLowerCase().includes(query.value))
}
const total = computed(() => groups.value.reduce((sum, group) => sum + group.packages.length, 0))

function key(group: Group, item: Package): string {
  return `${group.id}/${item.name}@${item.version}`
}

async function loadTexts(group: Group, item: Package, event: Event): Promise<void> {
  if (!(event.target as HTMLDetailsElement).open) return
  const id = key(group, item)
  if (texts.value[id]) return
  if (group.id === "web") {
    texts.value[id] = webPackages.value.find((entry) => entry.name === item.name)?.licenses ?? []
    return
  }
  texts.value[id] = "loading"
  try {
    const result = await apiJson<{ texts: LicenseText[] }>(
      `/api/about/licenses/${group.id}/${encodeURIComponent(item.name)}`,
    )
    texts.value[id] = result.texts
  } catch (reason) {
    texts.value[id] = reason instanceof Error ? reason.message : String(reason)
  }
}
</script>

<template>
  <div class="about-panel">
    <section class="about-version">
      <img src="/brand/header-logo.svg" alt="Vocalika" />
      <div>
        <strong>{{ about ? `Version ${about.version}` : "Version …" }}</strong>
        <span v-if="about">{{ about.desktop ? "Desktop app" : "In the browser" }} · {{ about.platform }}</span>
      </div>
      <div class="about-actions">
        <button type="button" class="ghost-button compact" @click="emit('whatsNew')">WHAT'S NEW</button>
        <button type="button" class="ghost-button compact" @click="emit('tour')">WELCOME TOUR</button>
      </div>
    </section>

    <section class="about-free">
      <p>
        Vocalika is built on the shoulders of giants. It sits on top of a great many free and open source
        projects, the work of thousands of people who gave it away, and making it free is a small way of giving
        something back.
      </p>
      <p>
        It is yours to use, study and change, under the
        <a href="https://github.com/gonzalocasas/vocalika/blob/main/LICENSE" target="_blank" rel="noopener" @click="openExternal">MIT license</a>.
        Copyright © 2026 Gonzalo Casas.
      </p>
      <ul class="about-giants" aria-label="Some of the projects Vocalika is built on">
        <li v-for="giant in GIANTS" :key="giant.name">
          <a :href="giant.url" target="_blank" rel="noopener" @click="openExternal">{{ giant.name }}</a>
          <span>{{ giant.what }}</span>
        </li>
      </ul>
    </section>

    <section>
      <h4 class="about-heading">MODELS, SOUNDS AND SERVICES</h4>
      <ul class="about-credits">
        <li v-for="credit in MODELS_AND_MEDIA" :key="credit.name">
          <div>
            <a :href="credit.url" target="_blank" rel="noopener" @click="openExternal">{{ credit.name }}</a>
            <a class="about-license" :href="credit.licenseUrl" target="_blank" rel="noopener" @click="openExternal">{{ credit.license }}</a>
          </div>
          <small>{{ credit.by }}</small>
          <p>{{ credit.what }}</p>
          <p v-if="credit.note" class="about-note" :class="{ warn: credit.warn }">{{ credit.note }}</p>
        </li>
      </ul>
    </section>

    <section>
      <h4 class="about-heading">OPEN SOURCE LICENSES<span v-if="total"> · {{ total }} PACKAGES</span></h4>
      <p class="about-lede">
        Every package Vocalika runs on, read from what is installed, with the license texts their authors ship.
      </p>
      <input
        v-model="filter"
        class="graphite-input about-filter"
        type="search"
        placeholder="Filter by name or license"
        aria-label="Filter packages by name or license"
      />
      <p v-if="error" class="inline-error">{{ error }}</p>
      <details v-for="group in groups" :key="group.id" class="about-group" :open="!!query">
        <summary>
          <b>{{ group.title }}</b>
          <span>{{ group.what }} · {{ visible(group).length }}</span>
        </summary>
        <details
          v-for="item in visible(group)"
          :key="key(group, item)"
          class="about-package"
          @toggle="loadTexts(group, item, $event)"
        >
          <summary>
            <span>{{ item.name }} <i>{{ item.version }}</i></span>
            <span class="about-license">{{ item.license }}</span>
          </summary>
          <div class="about-texts">
            <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" @click="openExternal">{{ item.url }}</a>
            <p v-if="texts[key(group, item)] === 'loading'" class="about-lede">Loading…</p>
            <p v-else-if="typeof texts[key(group, item)] === 'string'" class="inline-error">{{ texts[key(group, item)] }}</p>
            <template v-else-if="Array.isArray(texts[key(group, item)])">
              <p v-if="!(texts[key(group, item)] as LicenseText[]).length" class="about-lede">
                This package ships no license file; its license is {{ item.license }}, as published at the link above.
              </p>
              <div v-for="text in texts[key(group, item)] as LicenseText[]" :key="text.file">
                <small>{{ text.file }}</small>
                <pre>{{ text.text }}</pre>
              </div>
            </template>
          </div>
        </details>
      </details>
    </section>

    <footer class="about-footer">
      <p>
        Vocalika is
        <a href="https://github.com/gonzalocasas/vocalika/blob/main/LICENSE" target="_blank" rel="noopener" @click="openExternal">Free and Open Source Software</a>,
        made with ❤️ in Zurich
      </p>
    </footer>
  </div>
</template>
