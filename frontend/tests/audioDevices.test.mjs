import assert from "node:assert/strict"
import { test } from "node:test"

import { resolve } from "../src/shared/audioDevices.ts"

const devices = [
  { id: "a1", label: "MacBook Pro Microphone" },
  { id: "b2", label: "Scarlett 2i2 USB" },
]

test("nothing remembered means the system default", () => {
  assert.equal(resolve(null, devices), null)
})

test("a remembered device is found by id", () => {
  assert.deepEqual(resolve({ id: "b2", label: "renamed" }, devices), devices[1])
})

test("a device whose id changed is found again by name", () => {
  // Browsers re-key device ids per site, so the name is what survives.
  assert.deepEqual(resolve({ id: "old", label: "Scarlett 2i2 USB" }, devices), devices[1])
})

test("an unplugged device is not found", () => {
  assert.equal(resolve({ id: "zz", label: "AirPods Pro" }, devices), null)
})

test("before the microphone is opened no device can be matched, so nothing is called missing", () => {
  // WebKit lists no names until then; callers must not report this as unplugged.
  assert.equal(resolve({ id: "b2", label: "Scarlett 2i2 USB" }, []), null)
})
