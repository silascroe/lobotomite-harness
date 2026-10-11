import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
const script = await readFile(new URL("./preview.js", import.meta.url), "utf8");
const styles = await readFile(new URL("./preview.css", import.meta.url), "utf8");
const workflow = await readFile(new URL("../.github/workflows/pages.yml", import.meta.url), "utf8");

test("preview is clearly read-only and uses relative Pages assets", () => {
  assert.match(html, /STATIC PREVIEW/);
  assert.match(html, /cannot access your computer/);
  assert.match(html, /assets\/agent-lab\.css/);
  assert.match(html, /assets\/preview\.css/);
  assert.match(html, /src="preview\.js"/);
  assert.match(html, /textarea[^>]*disabled/);
});

test("preview exposes working Runs, Chats, and Details controls", () => {
  assert.match(html, /data-preview-mode="runs"/);
  assert.match(html, /data-preview-mode="chats"/);
  assert.match(html, /id="previewInspector"/);
  assert.match(script, /function selectMode/);
  assert.match(script, /function setInspectorOpen/);
  assert.match(script, /ArrowLeft.*ArrowRight.*Home.*End/);
});

test("static preview cannot call a local or remote model endpoint", () => {
  assert.doesNotMatch(script, /\bfetch\s*\(|XMLHttpRequest|WebSocket|127\.0\.0\.1|\/api\//i);
  assert.match(html, /No model is connected/);
  assert.match(html, /no model call occurred/);
});

test("Pages workflow tests and deploys only a static artifact", () => {
  assert.match(workflow, /node --test site\/test_preview\.mjs/);
  assert.match(workflow, /actions\/upload-pages-artifact@v4/);
  assert.match(workflow, /actions\/deploy-pages@v4/);
  assert.match(workflow, /pages: write/);
  assert.match(workflow, /id-token: write/);
  assert.match(styles, /@media \(max-width: 760px\)/);
  assert.match(styles, /overflow-y: auto/);
});
