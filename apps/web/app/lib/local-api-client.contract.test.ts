import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "./local-api-client.ts"), "utf-8");

test("local api client no longer depends on tauri invoke bridge", () => {
  assert.doesNotMatch(source, /@tauri-apps\/api\/core/);
  assert.doesNotMatch(source, /local_api_request/);
  assert.doesNotMatch(source, /__TAURI_INTERNALS__|__TAURI__/);
});

test("local api client keeps browser fetch fallback", () => {
  assert.match(source, /fetch\(`\$\{apiBase\(\)\}\$\{path\}`/);
});
