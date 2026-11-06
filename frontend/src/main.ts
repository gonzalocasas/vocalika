import { createApp } from "vue"
import App from "./App.vue"
import { primeDevices, vAudioOutput } from "./shared/audioDevices"
import "./style.css"

// v-audio-output keeps every player on the output chosen in the device picker.
createApp(App).directive("audio-output", vAudioOutput).mount("#app")
// Apply the saved microphone and output now, not only once Settings is opened.
void primeDevices()
