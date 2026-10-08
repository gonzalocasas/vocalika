<script setup lang="ts">
import type { TimedLine } from "./lyricsTiming"

/**
 * Lyric lines with the sung line and word lit. Renders only the lines, so the
 * parent owns the scrolling container and can find lines by `data-line`.
 * When `interactive`, any line or word asks to play from where it is sung.
 */
defineProps<{
  lines: TimedLine[]
  activeLine: number
  activeWord: number
  interactive?: boolean
}>()
const emit = defineEmits<{ play: [start: number] }>()

function play(start: number | null): void {
  if (start !== null) emit("play", start)
}
</script>

<template>
  <p
    v-for="(line, lineIndex) in lines"
    :key="lineIndex"
    :data-line="lineIndex"
    class="lyric-line"
    :class="{
      interactive,
      label: !line.sung && line.text,
      blank: !line.text,
      active: lineIndex === activeLine,
      past: activeLine >= 0 && lineIndex < activeLine,
    }"
    @click="interactive && play(line.start)"
  ><template v-for="(word, wordIndex) in line.words" :key="wordIndex"><span
    class="lyric-word"
    :class="{ timed: word.start !== null, sung: lineIndex === activeLine && wordIndex === activeWord }"
    @click.stop="interactive && play(word.start ?? line.start)"
  >{{ word.text }}</span>{{ " " }}</template><template v-if="!line.words.length">{{ line.text }}</template></p>
</template>
