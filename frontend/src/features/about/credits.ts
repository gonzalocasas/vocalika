/**
 * The credits the package lists cannot give: what each big piece does, and
 * the models, sounds and services, which come with licenses of their own.
 * The full list of open source packages is read from what is installed.
 */

export interface Credit {
  name: string
  url: string
  what: string
}

export interface Licensed extends Credit {
  /** Who made it, as their license asks to be credited. */
  by: string
  license: string
  licenseUrl: string
  note?: string
  /** A note that limits how it may be used, shown as a warning. */
  warn?: boolean
}

/** The same "giants" as the website. */
export const GIANTS: Credit[] = [
  { name: "Demucs", url: "https://github.com/facebookresearch/demucs", what: "pulls the voice out of the mix" },
  { name: "RMVPE", url: "https://github.com/Dream-High/RMVPE", what: "tracks pitch" },
  { name: "MMS", url: "https://pytorch.org/audio/stable/tutorials/forced_alignment_for_multilingual_data_tutorial.html", what: "times lyrics to the voice" },
  { name: "uroman", url: "https://github.com/isi-nlp/uroman", what: "spells lyrics in any script for it" },
  { name: "PyTorch", url: "https://pytorch.org", what: "runs the models" },
  { name: "FFmpeg", url: "https://ffmpeg.org", what: "reads and writes audio, via PyAV" },
  { name: "librosa, NumPy, SciPy", url: "https://librosa.org", what: "the signal processing" },
  { name: "yt-dlp", url: "https://github.com/yt-dlp/yt-dlp", what: "fetches songs" },
  { name: "LRCLIB", url: "https://lrclib.net", what: "finds the lyrics" },
  { name: "Vue, Plotly, FastAPI", url: "https://vuejs.org", what: "the app itself" },
  { name: "Tauri, uv", url: "https://tauri.app", what: "the desktop app and its installer" },
]

export const MODELS_AND_MEDIA: Licensed[] = [
  {
    name: "Demucs (htdemucs)",
    by: "Meta AI Research",
    url: "https://github.com/facebookresearch/demucs",
    what: "Vocal separation model, downloaded on first start.",
    license: "MIT",
    licenseUrl: "https://github.com/facebookresearch/demucs/blob/main/LICENSE",
  },
  {
    name: "RMVPE",
    by: "Haojie Wei et al.; weights published by the RVC Project",
    url: "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI",
    what: "Pitch tracking model, downloaded on first start.",
    license: "MIT",
    licenseUrl: "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/LICENSE",
  },
  {
    name: "MMS forced aligner",
    by: "Meta AI, “Scaling Speech Technology to 1,000+ Languages”, via torchaudio",
    url: "https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html",
    what: "Lyric timing model, downloaded on first start.",
    license: "CC BY-NC 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by-nc/4.0/",
    note: "For non-commercial use. Vocalika does not ship these weights; they come from Meta's servers.",
    warn: true,
  },
  {
    name: "uroman",
    by: "Ulf Hermjakob, USC Information Sciences Institute",
    url: "https://github.com/isi-nlp/uroman",
    what: "This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020).",
    license: "Apache-2.0",
    licenseUrl: "https://github.com/isi-nlp/uroman/blob/master/LICENSE.txt",
  },
  {
    name: "Salamander Grand Piano V3",
    by: "Alexander Holm",
    url: "https://archive.org/details/SalamanderGrandPianoV3",
    what: "The practice tones: one note every three semitones, C2 to C6, as MP3. Otherwise unaltered.",
    license: "CC BY 3.0",
    licenseUrl: "https://creativecommons.org/licenses/by/3.0/",
  },
  {
    name: "FFmpeg",
    by: "The FFmpeg developers, built into PyAV's packages",
    url: "https://ffmpeg.org",
    what: "Audio decoding and encoding.",
    license: "LGPL-3.0-or-later",
    licenseUrl: "https://ffmpeg.org/legal.html",
    note: "PyAV's packages also include the x264 and x265 video encoders (GPL-2.0-or-later), which Vocalika does not use.",
  },
  {
    name: "Space Grotesk, IBM Plex Mono",
    by: "Florian Karsten; IBM",
    url: "https://fonts.google.com",
    what: "The typefaces, loaded from Google Fonts.",
    license: "SIL OFL 1.1",
    licenseUrl: "https://openfontlicense.org",
  },
  {
    name: "LRCLIB",
    by: "The LRCLIB community",
    url: "https://lrclib.net",
    what: "Lyrics search. Lyrics belong to their writers and publishers.",
    license: "Service",
    licenseUrl: "https://lrclib.net",
  },
]
