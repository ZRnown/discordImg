import test from "node:test";
import assert from "node:assert/strict";

async function loadModule() {
  try {
    return await import(new URL("./image-filter-label.ts", import.meta.url));
  } catch {
    return {};
  }
}

test("formatSelectedImageFileLabel strips common image extensions", async () => {
  const { formatSelectedImageFileLabel } = await loadModule();

  assert.equal(typeof formatSelectedImageFileLabel, "function", "formatSelectedImageFileLabel should exist");
  assert.equal(formatSelectedImageFileLabel("summer.photo.JPG", 0), "summer.photo");
  assert.equal(formatSelectedImageFileLabel("avatar.png", 1), "avatar");
  assert.equal(formatSelectedImageFileLabel("cover.webp", 2), "cover");
});

test("formatSelectedImageFileLabel falls back to an ordinal label when no basename remains", async () => {
  const { formatSelectedImageFileLabel } = await loadModule();

  assert.equal(typeof formatSelectedImageFileLabel, "function", "formatSelectedImageFileLabel should exist");
  assert.equal(formatSelectedImageFileLabel(".jpeg", 0), "图片 1");
  assert.equal(formatSelectedImageFileLabel("   ", 1), "图片 2");
});
