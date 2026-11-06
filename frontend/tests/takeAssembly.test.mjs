import assert from "node:assert/strict"
import { test } from "node:test"

import { TakeAssembler, encodeWav } from "../src/features/recording/takeAssembly.ts"

/** A block whose samples are their own context frame numbers: easy to trace. */
const block = (frame, length = 128) => [Float32Array.from({ length }, (_, i) => frame + i)]

function feed(assembler, from, to) {
  for (let frame = from; frame < to; frame += 128) assembler.add(frame, block(frame))
}

test("the take starts exactly at the frame the backing track started", () => {
  const take = new TakeAssembler()
  take.open(300) // mid-block, as a scheduled start usually is
  feed(take, 0, 1024)
  take.close(800)
  const [channel] = take.build()
  assert.equal(channel.length, 500)
  assert.equal(channel[0], 300)
  assert.equal(channel.at(-1), 799)
})

test("a pause leaves no gap and no overlap: windows join end to end", () => {
  const take = new TakeAssembler()
  take.open(100)
  feed(take, 0, 512)
  take.close(400)
  feed(take, 512, 2048) // the paused stretch arrives and is ignored
  take.open(1500)
  feed(take, 2048, 2048) // nothing yet
  take.add(1408, block(1408)) // late block straddling the resume
  feed(take, 1536, 2048)
  take.close(1700)
  const [channel] = take.build()
  assert.equal(channel.length, 300 + 200)
  assert.equal(channel[299], 399)
  assert.equal(channel[300], 1500)
  assert.equal(channel.at(-1), 1699)
})

test("a block the audio thread skipped becomes silence in place, not a shift", () => {
  const take = new TakeAssembler()
  take.open(0)
  take.add(0, block(0))
  take.add(256, block(256)) // 128..255 never arrived
  take.close(384)
  const [channel] = take.build()
  assert.equal(channel[127], 127)
  assert.equal(channel[128], 0)
  assert.equal(channel[256], 256)
})

test("blocks without input keep the timeline and count as received", () => {
  const take = new TakeAssembler()
  take.open(0)
  take.add(0, []) // the microphone had not delivered yet
  take.add(128, block(128))
  take.close(256)
  assert.ok(take.complete())
  assert.deepEqual(Array.from(take.build()[0].subarray(126, 130)), [0, 0, 128, 129])
})

test("the take is complete only once the audio thread passed the last window", () => {
  const take = new TakeAssembler()
  take.open(0)
  feed(take, 0, 256)
  take.close(300)
  assert.equal(take.complete(), false)
  take.add(256, block(256))
  assert.equal(take.complete(), true)
  assert.equal(take.capturedFrames(), 300)
})

test("WAV output is 24-bit PCM with the right header and values", async () => {
  const blob = encodeWav([Float32Array.of(0, 1, -1, 0.5)], 48_000)
  const bytes = new Uint8Array(await blob.arrayBuffer())
  const view = new DataView(bytes.buffer)
  assert.equal(String.fromCharCode(...bytes.subarray(0, 4)), "RIFF")
  assert.equal(view.getUint16(22, true), 1) // channels
  assert.equal(view.getUint32(24, true), 48_000)
  assert.equal(view.getUint16(34, true), 24)
  assert.equal(view.getUint32(40, true), 12)
  const sample = (index) => {
    const at = 44 + index * 3
    const value = bytes[at] | (bytes[at + 1] << 8) | (bytes[at + 2] << 16)
    return value & 0x800000 ? value - 0x1000000 : value
  }
  assert.deepEqual([0, 1, 2, 3].map(sample), [0, 0x7fffff, -0x800000, Math.round(0.5 * 0x7fffff)])
})
