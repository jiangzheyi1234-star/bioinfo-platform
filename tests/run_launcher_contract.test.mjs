import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const source = readFileSync(resolve(import.meta.dirname, "../run.bat"), "utf-8").replace(/\r\n/g, "\n");

function section(label, nextLabel) {
  const marker = `\n${label}\n`;
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `missing section ${label}`);
  const nextMarker = nextLabel ? `\n${nextLabel}\n` : null;
  const bodyStart = start + marker.length;
  const end = nextMarker ? source.indexOf(nextMarker, bodyStart) : source.length;
  assert.notEqual(end, -1, `missing section boundary ${nextLabel}`);
  return source.slice(bodyStart, end);
}

test("desktop launcher avoids prestarting a separate api window", () => {
  const desktopSection = section(":desktop", ":desktop_built");
  assert.match(desktopSection, /Desktop dev will launch its own local backend/i);
  assert.doesNotMatch(desktopSection, /start "H2OMeta API"/i);
});

test("desktop built launcher avoids prestarting a separate api window", () => {
  const builtSection = section(":desktop_built", ":web");
  assert.match(builtSection, /Desktop shell will launch its own local backend/i);
  assert.doesNotMatch(builtSection, /start "H2OMeta API"/i);
});

test("web launcher still starts the standalone api window", () => {
  const webSection = section(":web", null);
  assert.match(webSection, /start "H2OMeta API"/i);
});
