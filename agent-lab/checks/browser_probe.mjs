#!/usr/bin/env node
// Behavioral browser probe for the catalog checkers.
//
// Usage: node browser_probe.mjs <static-page|mini-project> <url>
//
// Drives a locally installed Chromium-family browser (Edge, Chrome or
// Chromium) through the DevTools protocol with Node's built-in WebSocket, so
// the checkers need no npm packages and no browser download. The page is
// loaded from the checker's loopback server; every request to any other
// origin is blocked and recorded. The probe types, clicks, tabs and resizes
// like a person would, then prints raw observations as JSON. The Python
// checkers turn those observations into pass/fail checks.
//
// The page under test is model-written and untrusted. Probe helpers run in an
// isolated JavaScript world, so page scripts cannot tamper with them; they
// share only the DOM.

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

const DEADLINE_MS = 30000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class ProbeError extends Error {
  constructor(message, infrastructure = false) {
    super(message);
    this.infrastructure = infrastructure;
  }
}

// The page replaced its document (usually a form submission without
// preventDefault) while the probe was looking at it. Callers that expect this
// treat it as a navigation; anywhere else it is reported as page behavior.
class ContextLost extends ProbeError {
  constructor() {
    super("the page reloaded or navigated away while it was being checked");
  }
}

function findBrowser() {
  const override = process.env.AGENT_LAB_BROWSER;
  if (override) return existsSync(override) ? override : null;
  const env = process.env;
  const candidates = process.platform === "win32" ? [
    env["ProgramFiles(x86)"] && `${env["ProgramFiles(x86)"]}\\Microsoft\\Edge\\Application\\msedge.exe`,
    env.ProgramFiles && `${env.ProgramFiles}\\Microsoft\\Edge\\Application\\msedge.exe`,
    env.ProgramFiles && `${env.ProgramFiles}\\Google\\Chrome\\Application\\chrome.exe`,
    env["ProgramFiles(x86)"] && `${env["ProgramFiles(x86)"]}\\Google\\Chrome\\Application\\chrome.exe`,
    env.LOCALAPPDATA && `${env.LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe`,
  ] : process.platform === "darwin" ? [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ] : [
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
    "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge", "/snap/bin/chromium",
  ];
  return candidates.find((path) => path && existsSync(path)) ?? null;
}

async function launch(executable) {
  const profile = mkdtempSync(join(tmpdir(), "agent-lab-probe-"));
  const args = [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--disable-default-apps", "--mute-audio", "--hide-scrollbars",
    // Names never resolve, so a page cannot reach the internet even if a
    // request slipped past interception. Loopback stays reachable.
    "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
    "--window-size=1280,900", "about:blank",
  ];
  const child = spawn(executable, args, { stdio: ["ignore", "ignore", "pipe"], windowsHide: true });
  let stderr = "";
  const endpoint = await new Promise((resolve, reject) => {
    const timer = setInterval(() => {
      // Some builds only write the port file, not the stderr banner.
      const portFile = join(profile, "DevToolsActivePort");
      if (existsSync(portFile)) {
        let contents = "";
        try {
          contents = readFileSync(portFile, "utf8");
        } catch {
          // Windows reports EBUSY while the browser is still writing it.
          return;
        }
        const [port, path] = contents.split(/\r?\n/);
        if (port && path) finish(null, `ws://127.0.0.1:${port}${path}`);
      }
    }, 100);
    const timeout = setTimeout(() => finish(new ProbeError("browser did not start within 10 s", true)), 10000);
    function finish(error, url) {
      clearInterval(timer);
      clearTimeout(timeout);
      error ? reject(error) : resolve(url);
    }
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(stderr);
      if (match) finish(null, match[1]);
    });
    child.on("error", (error) => finish(new ProbeError(`could not start browser: ${error.message}`, true)));
    child.on("exit", (code) => finish(new ProbeError(`browser exited early (code ${code})`, true)));
  });
  return { child, profile, endpoint };
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Set();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const waiter = this.pending.get(message.id);
        if (!waiter) return;
        this.pending.delete(message.id);
        // A protocol error is the probe failing, not the page; Page.eval
        // turns the one expected case (a vanished context) into ContextLost.
        if (message.error) waiter.reject(new ProbeError(`${waiter.method}: ${message.error.message}`, true));
        else waiter.resolve(message.result);
      } else {
        for (const listener of this.listeners) listener(message);
      }
    });
    socket.addEventListener("close", () => {
      for (const waiter of this.pending.values()) waiter.reject(new ProbeError("browser connection closed", true));
      this.pending.clear();
    });
  }

  static connect(url) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.addEventListener("open", () => resolve(new Cdp(socket)), { once: true });
      socket.addEventListener("error", () => reject(new ProbeError("could not connect to the browser", true)), { once: true });
    });
  }

  send(method, params = {}, sessionId) {
    const id = ++this.nextId;
    this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject, method }));
  }
}

class Page {
  constructor(cdp, sessionId, origin) {
    this.cdp = cdp;
    this.sessionId = sessionId;
    this.origin = origin;
    this.exceptions = [];
    this.consoleErrors = [];
    this.requests = new Map();
    this.remote = [];
    this.dialogs = [];
    this.navigations = 0;
    this.loadWaiters = [];
    this.contextId = null;
    this.contextLost = false;
    this.loadedSinceNavigation = false;
    cdp.listeners.add((message) => {
      if (message.sessionId !== sessionId) return;
      this.onEvent(message.method, message.params);
    });
  }

  send(method, params = {}) {
    return this.cdp.send(method, params, this.sessionId);
  }

  onEvent(method, params) {
    switch (method) {
      case "Fetch.requestPaused": {
        const url = params.request.url;
        if (url.startsWith(this.origin + "/")) {
          this.send("Fetch.continueRequest", { requestId: params.requestId }).catch(() => {});
        } else {
          if (this.remote.length < 10) this.remote.push(url.slice(0, 160));
          this.send("Fetch.failRequest", { requestId: params.requestId, errorReason: "BlockedByClient" }).catch(() => {});
        }
        break;
      }
      case "Network.responseReceived": {
        const url = params.response.url;
        if (url.startsWith(this.origin + "/")) {
          this.requests.set(new URL(url).pathname, params.response.status);
        }
        break;
      }
      case "Runtime.exceptionThrown": {
        const details = params.exceptionDetails;
        const text = details.exception?.description || details.text || "uncaught exception";
        const where = details.url ? `${basename(new URL(details.url).pathname)}:${details.lineNumber + 1}: ` : "";
        if (this.exceptions.length < 5) this.exceptions.push((where + text.split("\n")[0]).slice(0, 200));
        break;
      }
      case "Runtime.consoleAPICalled": {
        if (params.type === "error" && this.consoleErrors.length < 5) {
          const first = params.args?.[0];
          this.consoleErrors.push(String(first?.value ?? first?.description ?? "console.error").slice(0, 200));
        }
        break;
      }
      case "Page.javascriptDialogOpening": {
        // alert() and confirm() would freeze a headless page until the deadline.
        if (this.dialogs.length < 5) this.dialogs.push(`${params.type}: ${String(params.message).slice(0, 120)}`);
        this.send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {});
        break;
      }
      case "Page.frameNavigated": {
        if (!params.frame.parentId) {
          this.navigations += 1;
          this.loadedSinceNavigation = false;
        }
        break;
      }
      // These arrive before frameNavigated when a document is replaced, so a
      // poll that lands in between knows not to touch the old context.
      case "Runtime.executionContextsCleared":
        this.markContextLost();
        break;
      case "Runtime.executionContextDestroyed":
        if (params.executionContextId === this.contextId) this.markContextLost();
        break;
      case "Page.loadEventFired": {
        this.loadedSinceNavigation = true;
        const waiters = this.loadWaiters;
        this.loadWaiters = [];
        for (const resolve of waiters) resolve();
        break;
      }
      default:
        break;
    }
  }

  async init() {
    await this.send("Page.enable");
    await this.send("Runtime.enable");
    await this.send("Network.enable");
    await this.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
    await this.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    await this.send("Page.bringToFront");
  }

  async viewport(width, height, mobile) {
    await this.send("Emulation.setDeviceMetricsOverride", {
      width, height, deviceScaleFactor: 1, mobile, screenWidth: width, screenHeight: height,
    });
  }

  waitForLoad(timeout = 8000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new ProbeError("page did not finish loading within 8 s")), timeout);
      this.loadWaiters.push(() => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  async load(url) {
    const loaded = this.waitForLoad();
    const result = await this.send("Page.navigate", { url });
    if (result.errorText) throw new ProbeError(`could not load the page: ${result.errorText}`);
    await loaded;
    await sleep(300);
    await this.installHelpers();
  }

  markContextLost() {
    this.contextLost = true;
    this.loadedSinceNavigation = false;
  }

  navigatedSince(count) {
    return this.navigations > count || this.contextLost;
  }

  async afterNavigation() {
    // A form submission that reloads the page: wait for the new document.
    if (!this.loadedSinceNavigation) {
      try {
        await this.waitForLoad(4000);
      } catch {
        // Continue with whatever document is there.
      }
    }
    await sleep(200);
    await this.installHelpers();
  }

  async installHelpers() {
    const { frameTree } = await this.send("Page.getFrameTree");
    const { executionContextId } = await this.send("Page.createIsolatedWorld", {
      frameId: frameTree.frame.id, worldName: "agent-lab-probe",
    });
    this.contextId = executionContextId;
    this.contextLost = false;
    await this.eval(`(${installHelpers.toString()})()`);
  }

  async eval(expression) {
    if (this.contextLost) throw new ContextLost();
    let result;
    try {
      result = await this.send("Runtime.evaluate", {
        expression, contextId: this.contextId, awaitPromise: true, returnByValue: true,
      });
    } catch (error) {
      if (/context/i.test(error.message)) {
        this.markContextLost();
        throw new ContextLost();
      }
      throw error;
    }
    if (result.exceptionDetails) {
      const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
      // The helpers are meant to cope with any DOM; one throwing is a probe bug.
      throw new ProbeError(`probe helper failed: ${String(text).split("\n")[0]}`, true);
    }
    return result.result.value;
  }

  async key(name) {
    const keys = {
      Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
      Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 },
    };
    const spec = keys[name];
    // Enter needs its text on keyDown to produce the keypress that activates
    // buttons and submits forms.
    const text = name === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {};
    await this.send("Input.dispatchKeyEvent", { type: "keyDown", ...spec, ...text });
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", ...spec });
  }

  async click(x, y) {
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await this.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
  }

  async type(text) {
    await this.send("Input.insertText", { text });
  }
}

// Everything below runs inside the page's isolated world. It must be
// self-contained: it is serialized with Function.prototype.toString.
function installHelpers() {
  const SKIP = new Set(["script", "style", "template", "noscript", "head", "meta", "link", "title", "option"]);
  const norm = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
  const EMPTY = /\b(no|none|nothing|empty|yet|first|start|begin|haven'?t|zero)\b/i;
  const state = {};

  function visible(el) {
    if (!el || !el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 2 && rect.height >= 2;
  }

  function ownText(el) {
    let text = "";
    for (const node of el.childNodes) if (node.nodeType === 3) text += node.textContent + " ";
    return norm(text);
  }

  function pathOf(el) {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.documentElement) {
      let part = el.localName;
      if (el.id) {
        parts.unshift(`${part}#${CSS.escape(el.id)}`);
        return parts.join(">");
      }
      const parent = el.parentElement;
      if (parent) {
        const same = [...parent.children].filter((child) => child.localName === el.localName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(el) + 1})`;
      }
      parts.unshift(part);
      el = parent;
    }
    return parts.join(">");
  }

  function accName(el) {
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const text = labelledby.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ");
      if (norm(text)) return norm(text);
    }
    if (norm(el.getAttribute("aria-label"))) return norm(el.getAttribute("aria-label"));
    if (el.labels && el.labels.length) {
      const text = [...el.labels].map((label) => label.textContent).join(" ");
      if (norm(text)) return norm(text);
    }
    if (el.localName === "input" && ["submit", "button", "reset"].includes(el.type)) return norm(el.value);
    if (!["input", "textarea", "select"].includes(el.localName) && norm(el.textContent)) return norm(el.textContent);
    return norm(el.getAttribute("title"));
  }

  function describe(el) {
    if (!el) return "nothing";
    let text = el.localName;
    if (el.id) text += `#${el.id}`;
    else if (el.classList.length) text += `.${el.classList[0]}`;
    const name = accName(el);
    if (name) text += ` "${name.slice(0, 40)}"`;
    return text;
  }

  function elements() {
    return [...document.body.querySelectorAll("*")].filter((el) => !SKIP.has(el.localName)).slice(0, 4000);
  }

  // Color math. Any CSS color, including oklch(), is resolved by painting it.
  const ctx = new OffscreenCanvas(1, 1).getContext("2d", { willReadFrequently: true });
  function rgba(color) {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "rgba(0, 0, 0, 0)";
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, 1, 1);
    const data = ctx.getImageData(0, 0, 1, 1).data;
    return [data[0], data[1], data[2], data[3] / 255];
  }
  function blend(top, bottom) {
    const alpha = top[3] + bottom[3] * (1 - top[3]);
    if (alpha === 0) return [0, 0, 0, 0];
    return [0, 1, 2].map((i) => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / alpha).concat(alpha);
  }
  function luminance(color) {
    const [r, g, b] = color.slice(0, 3).map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function ratio(a, b) {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  }
  // Possible backgrounds behind an element: gradients contribute each stop,
  // so text is judged against the worst spot it could sit on. A url() image
  // makes the background unknowable and the element is skipped.
  function backgrounds(el) {
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      const image = style.backgroundImage;
      if (image && image !== "none") {
        if (/url\(/.test(image)) return null;
        const stops = (image.match(/rgba?\([^)]*\)|#[0-9a-f]{3,8}\b|oklch\([^)]*\)|hsla?\([^)]*\)/gi) || []).map(rgba);
        if (!stops.length) return null;
        layers.push(stops);
        if (stops.every((stop) => stop[3] >= 0.999)) break;
      }
      const color = rgba(style.backgroundColor);
      if (color[3] > 0) {
        layers.push([color]);
        if (color[3] >= 0.999 && !(image && image !== "none")) break;
      }
    }
    let candidates = [[255, 255, 255, 1]];
    for (const layer of layers.reverse()) {
      const next = [];
      for (const base of candidates) for (const color of layer) next.push(blend(color, base));
      candidates = next.slice(0, 16);
    }
    return candidates;
  }

  function styleOf(el) {
    const s = getComputedStyle(el);
    return {
      outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth, outlineColor: s.outlineColor,
      outlineOffset: s.outlineOffset, boxShadow: s.boxShadow, backgroundColor: s.backgroundColor,
      color: s.color, textDecorationLine: s.textDecorationLine,
      borderTopColor: s.borderTopColor, borderBottomColor: s.borderBottomColor,
      borderLeftColor: s.borderLeftColor, borderRightColor: s.borderRightColor,
      borderTopWidth: s.borderTopWidth, borderBottomWidth: s.borderBottomWidth,
    };
  }
  function settle() {
    for (const animation of document.getAnimations()) {
      try {
        animation.finish();
      } catch {
        // Infinite animations cannot finish; their current frame stands.
      }
    }
  }
  function indicatorChanged(focused, base, own) {
    if (!base) return false;
    const outline = focused.outlineStyle !== "none" && (focused.outlineStyle === "auto" || parseFloat(focused.outlineWidth) > 0)
      && rgba(focused.outlineColor)[3] > 0;
    const outlineChanged = ["outlineStyle", "outlineWidth", "outlineColor", "outlineOffset"].some((k) => focused[k] !== base[k]);
    if (outline && outlineChanged) return true;
    if (focused.boxShadow !== "none" && focused.boxShadow !== base.boxShadow) return true;
    const keys = ["borderTopColor", "borderBottomColor", "borderLeftColor", "borderRightColor", "borderTopWidth", "borderBottomWidth"];
    if (own) keys.push("backgroundColor", "color", "textDecorationLine");
    return keys.some((k) => focused[k] !== base[k]);
  }
  const FOCUSABLE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex='-1']), [contenteditable='true']";

  globalThis.__probe = {
    staticStructure() {
      const headings = [...document.querySelectorAll("h1, h2")].filter(visible).map((el) => norm(el.textContent));
      const actions = [...document.querySelectorAll("button, a[href], input[type=submit], input[type=button], [role=button]")].filter(visible);
      const add = actions.find((el) => /\badd\b(\s+an?)?(\s+new)?\s+observations?\b/i.test(accName(el)));
      return {
        headings: headings.slice(0, 4),
        productHeading: headings.some((text) => /northstar\s+field\s+notes/i.test(text)),
        addAction: add ? describe(add) : null,
        header: Boolean(document.querySelector("header, [role=banner]")),
        main: Boolean(document.querySelector("main, [role=main]")),
        form: Boolean(document.querySelector("form")),
      };
    },

    miniStructure() {
      const h1 = [...document.querySelectorAll("h1")].filter(visible).map((el) => norm(el.textContent));
      const paragraphs = [...document.querySelectorAll("p")].filter(visible).map((el) => norm(el.textContent));
      return {
        headings: h1.slice(0, 3),
        heading: h1.some((text) => /signal\s+garden/i.test(text)),
        description: paragraphs.some((text) => text.length >= 10),
        main: Boolean(document.querySelector("main, [role=main]")),
      };
    },

    resolveFields() {
      const controls = [...document.querySelectorAll("input, textarea, select")].filter((el) =>
        !["hidden", "submit", "button", "reset", "checkbox", "radio", "file", "image", "range", "color"].includes((el.type || "").toLowerCase()));
      const patterns = {
        title: /\btitle\b/i,
        location: /\b(location|place|where|site|spot)\b/i,
        note: /\b(notes?|details?|description|observation text|what did you)\b/i,
      };
      const used = new Set();
      const result = {};
      state.fields = {};
      for (const [key, pattern] of Object.entries(patterns)) {
        let el = controls.find((c) => !used.has(c) && pattern.test(accName(c)));
        let labeled = Boolean(el);
        if (!el) el = controls.find((c) => !used.has(c) && pattern.test([c.name, c.id, c.placeholder].join(" ")));
        if (!el && key === "note") {
          el = controls.find((c) => !used.has(c) && c.localName === "textarea");
          labeled = false;
        }
        if (el) used.add(el);
        state.fields[key] = el || null;
        result[key] = el ? { found: true, labeled, visible: visible(el), kind: el.localName === "select" ? "select" : "text", name: accName(el) } : { found: false };
      }
      return result;
    },

    focusField(key) {
      const el = state.fields?.[key];
      if (!el || !el.isConnected) return { ok: false };
      el.scrollIntoView({ block: "center" });
      if (el.localName === "select") {
        const option = el.options[Math.min(1, el.options.length - 1)];
        if (!option) return { ok: false };
        el.value = option.value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true, kind: "select", value: norm(option.textContent) };
      }
      el.focus();
      el.value = "";
      return { ok: document.activeElement === el, kind: "text" };
    },

    // Where a person would click to submit: the form's submit control, else
    // a visible button that reads like adding or saving.
    submitTarget() {
      const form = Object.values(state.fields || {}).find((el) => el?.form)?.form || document.querySelector("form");
      let target = form?.querySelector("button:not([type]), button[type=submit], input[type=submit], input[type=image]");
      if (!target || !visible(target)) {
        target = [...document.querySelectorAll("button, input[type=button], [role=button]")].filter(visible)
          .find((el) => /\b(add|save|submit|record|log|create)\b/i.test(accName(el)));
      }
      return this.pointAt(target);
    },

    pointAt(el) {
      if (!el || !visible(el)) return { ok: false };
      el.scrollIntoView({ block: "center" });
      const rect = el.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      const hit = document.elementFromPoint(x, y);
      return { ok: true, x, y, desc: describe(el), path: pathOf(el), covered: Boolean(hit && hit !== el && !el.contains(hit)) ? describe(hit) : null };
    },

    clickAction(pattern) {
      const re = new RegExp(pattern, "i");
      const el = [...document.querySelectorAll("button, a[href], input[type=button], input[type=submit], [role=button]")]
        .filter(visible).find((c) => re.test(accName(c)));
      return this.pointAt(el);
    },

    primaryAction() {
      const scope = document.querySelector("main, [role=main]") || document.body;
      const buttons = [...scope.querySelectorAll("button, input[type=button], input[type=submit], [role=button]")]
        .filter((el) => visible(el) && el.type !== "reset" && !el.disabled);
      return this.pointAt(buttons[0]);
    },

    findCard(tokens) {
      const has = (el, token) => el.textContent.toLowerCase().includes(String(token).toLowerCase());
      const holders = elements().filter((el) => has(el, tokens.title) && visible(el) && !el.closest("form"));
      if (!holders.length) return { found: false };
      const deepest = holders.filter((el) => ![...el.children].some((child) => has(child, tokens.title)));
      for (const el of deepest) {
        for (let node = el; node && node !== document.body; node = node.parentElement) {
          if (has(node, tokens.location) && has(node, tokens.note)) {
            return { found: true, complete: true, containsForm: Boolean(node.matches("form") || node.querySelector("form")), desc: describe(node) };
          }
        }
      }
      return { found: true, complete: false, desc: describe(deepest[0]) };
    },

    textState() {
      const texts = {};
      const numbers = {};
      for (const el of elements()) {
        const text = ownText(el);
        if (!text || !visible(el)) continue;
        const path = pathOf(el);
        texts[path] = text.slice(0, 160);
        const found = text.match(/\b\d+\b/g);
        if (found) numbers[path] = found.map(Number).slice(0, 5);
      }
      return { texts, numbers };
    },

    emptyCandidates(texts) {
      return Object.entries(texts).filter(([, text]) => EMPTY.test(text) && text.length <= 160).map(([path, text]) => ({ path, text }));
    },

    activePath() {
      const el = document.activeElement;
      return el && el !== document.body ? pathOf(el) : null;
    },

    prepareFocus() {
      document.activeElement?.blur?.();
      window.scrollTo(0, 0);
      settle();
      state.base = {};
      for (const el of document.querySelectorAll(FOCUSABLE)) {
        for (let node = el, depth = 0; node && depth < 3; node = node.parentElement, depth += 1) {
          const path = pathOf(node);
          if (!state.base[path]) state.base[path] = styleOf(node);
        }
      }
    },

    focusInfo() {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return { path: null };
      settle();
      let indicator = indicatorChanged(styleOf(el), state.base?.[pathOf(el)], true);
      // A wrapper styled with :focus-within also counts as the indicator.
      for (let node = el.parentElement, depth = 0; !indicator && node && depth < 2; node = node.parentElement, depth += 1) {
        indicator = indicatorChanged(styleOf(node), state.base?.[pathOf(node)], false);
      }
      return { path: pathOf(el), desc: describe(el), indicator, visible: visible(el) };
    },

    layout() {
      const root = document.documentElement;
      const width = root.clientWidth;
      const scrollWidth = Math.max(root.scrollWidth, document.body?.scrollWidth || 0);
      const offenders = [];
      for (const el of elements()) {
        if (offenders.length >= 3) break;
        if (!visible(el)) continue;
        if (!ownText(el) && !el.matches("input, textarea, select, button, img, svg, video, canvas")) continue;
        const rect = el.getBoundingClientRect();
        const partlyRight = rect.left < width && rect.right > width + 1;
        const partlyLeft = rect.right > 0 && rect.left < -1;
        if (partlyRight || partlyLeft) offenders.push(`${describe(el)} spans ${Math.round(rect.left)}-${Math.round(rect.right)}px`);
      }
      return { width, scrollWidth, viewportMeta: Boolean(document.querySelector("meta[name=viewport]")), offenders };
    },

    contrast(minimum) {
      settle();
      let checked = 0;
      let unknown = 0;
      const failures = [];
      for (const el of elements()) {
        if (!ownText(el) || !visible(el) || el.closest("[aria-hidden=true]") || el.matches(":disabled")) continue;
        const fg = rgba(getComputedStyle(el).color);
        const bgs = backgrounds(el);
        if (!bgs || fg[3] < 0.1) {
          unknown += 1;
          continue;
        }
        checked += 1;
        const worst = Math.min(...bgs.map((bg) => ratio(blend(fg, bg), bg)));
        if (worst < minimum && failures.length < 5) failures.push({ desc: describe(el), text: ownText(el).slice(0, 40), ratio: Math.round(worst * 100) / 100 });
      }
      return { checked, unknown, failures };
    },
  };
}

async function focusWalk(page, limit = 14) {
  await page.eval("__probe.prepareFocus()");
  const stops = [];
  const seen = new Set();
  for (let i = 0; i < limit; i += 1) {
    await page.key("Tab");
    await sleep(40);
    const info = await page.eval("__probe.focusInfo()");
    if (!info.path || seen.has(info.path)) break;
    seen.add(info.path);
    stops.push(info);
  }
  await page.eval("document.activeElement?.blur?.()");
  return stops;
}

async function waitFor(check, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      if (await check()) return true;
    } catch (error) {
      if (error instanceof ContextLost) return true;
      throw error;
    }
    await sleep(100);
  }
  return false;
}

// A submit handler can update the page and still let the browser submit the
// form; the reload then lands a moment later. Wait briefly before deciding.
const LATE_NAVIGATION_MS = 300;

function changedTexts(before, after, excludePath) {
  const changed = [];
  for (const [path, text] of Object.entries(after.texts)) {
    if (excludePath && (path === excludePath || path.startsWith(excludePath + ">"))) continue;
    if (before.texts[path] !== text) changed.push({ path, before: before.texts[path] ?? null, after: text });
  }
  return changed.slice(0, 5);
}

const OBSERVATIONS = [
  { title: "Kestrel Vupo", location: "Ridge Wuxa", note: "Hovering over the meadow Zelq" },
  { title: "Heron Dravik", location: "Marsh Tolup", note: "Fishing in the reeds Quoba" },
];

async function submitObservation(page, tokens) {
  const record = { attempted: false, filled: {} };
  for (const key of ["title", "location", "note"]) {
    const field = await page.eval(`__probe.focusField(${JSON.stringify(key)})`);
    record.filled[key] = field.ok;
    if (field.ok && field.kind === "text") await page.type(tokens[key]);
    if (field.ok && field.kind === "select") tokens = { ...tokens, [key]: field.value };
  }
  if (!record.filled.title || !record.filled.note) return record;
  const target = await page.eval("__probe.submitTarget()");
  if (!target.ok) return { ...record, noTarget: true };
  record.attempted = true;
  record.control = target.desc;
  record.covered = target.covered;
  const before = page.navigations;
  await page.click(target.x, target.y);
  await waitFor(async () => page.navigatedSince(before) || (await page.eval(`__probe.findCard(${JSON.stringify(tokens)})`)).found, 2000);
  await sleep(LATE_NAVIGATION_MS);
  try {
    if (page.navigatedSince(before)) throw new ContextLost();
    record.card = await page.eval(`__probe.findCard(${JSON.stringify(tokens)})`);
    record.state = await page.eval("__probe.textState()");
  } catch (error) {
    if (!(error instanceof ContextLost)) throw error;
    await page.afterNavigation();
    return { ...record, navigated: true };
  }
  return record;
}

async function staticPage(page, url) {
  const obs = {};
  await page.viewport(1280, 900, false);
  await page.load(url);
  obs.structure = await page.eval("__probe.staticStructure()");
  obs.focus = await focusWalk(page);
  let fields = await page.eval("__probe.resolveFields()");
  const hidden = ["title", "note"].some((key) => fields[key].found && !fields[key].visible);
  if (hidden) {
    // The form may open from the hero's "Add observation" action.
    const opener = await page.eval(`__probe.clickAction(${JSON.stringify("\\badd\\b.*observation")})`);
    if (opener.ok) {
      const before = page.navigations;
      await page.click(opener.x, opener.y);
      await sleep(400);
      obs.openedForm = opener.desc;
      if (page.navigatedSince(before)) {
        obs.openerNavigated = true;
        await page.afterNavigation();
      }
      fields = await page.eval("__probe.resolveFields()");
    }
  }
  obs.fields = fields;
  obs.before = await page.eval("__probe.textState()");
  obs.emptyCandidates = await page.eval(`__probe.emptyCandidates(${JSON.stringify(obs.before.texts)})`);
  obs.submissions = [];
  for (const tokens of OBSERVATIONS) {
    const result = await submitObservation(page, tokens);
    obs.submissions.push(result);
    if (!result.attempted || result.navigated) break;
  }
  if (obs.submissions.length === 2 && obs.submissions[1].card) {
    obs.firstStillShown = await page.eval(`__probe.findCard(${JSON.stringify(OBSERVATIONS[0])})`);
  }
  obs.contrast = await page.eval("__probe.contrast(3)");
  obs.desktop = await page.eval("__probe.layout()");
  await page.viewport(375, 812, true);
  await page.load(url);
  obs.phone = await page.eval("__probe.layout()");
  return obs;
}

async function miniProject(page, url) {
  const obs = {};
  await page.viewport(1280, 900, false);
  await page.load(url);
  obs.structure = await page.eval("__probe.miniStructure()");
  obs.focus = await focusWalk(page);
  obs.desktop = await page.eval("__probe.layout()");
  const before = await page.eval("__probe.textState()");
  const target = await page.eval("__probe.primaryAction()");
  obs.action = target.ok ? { desc: target.desc, covered: target.covered } : null;
  if (target.ok) {
    const navigations = page.navigations;
    await page.click(target.x, target.y);
    let changed = [];
    await waitFor(async () => {
      if (page.navigatedSince(navigations)) return true;
      changed = changedTexts(before, await page.eval("__probe.textState()"), target.path);
      return changed.length > 0;
    }, 1500);
    await sleep(LATE_NAVIGATION_MS);
    // The page is reloaded next anyway, so a navigation needs no recovery here.
    obs.click = page.navigatedSince(navigations) ? { navigated: true, changed: [] } : { navigated: false, changed };
    // Keyboard: a fresh page, Tab to the same control, press Enter.
    await page.load(url);
    const fresh = await page.eval("__probe.textState()");
    let reached = false;
    for (let i = 0; i < 15 && !reached; i += 1) {
      await page.key("Tab");
      await sleep(30);
      reached = (await page.eval("__probe.activePath()")) === target.path;
    }
    obs.keyboard = { reached, changed: [] };
    if (reached) {
      const navigations2 = page.navigations;
      await page.key("Enter");
      await waitFor(async () => {
        if (page.navigatedSince(navigations2)) return true;
        obs.keyboard.changed = changedTexts(fresh, await page.eval("__probe.textState()"), target.path);
        return obs.keyboard.changed.length > 0;
      }, 1500);
      await sleep(LATE_NAVIGATION_MS);
      obs.keyboard.navigated = page.navigatedSince(navigations2);
    }
  }
  await page.viewport(375, 812, true);
  await page.load(url);
  obs.phone = await page.eval("__probe.layout()");
  return obs;
}

const SCENARIOS = { "static-page": staticPage, "mini-project": miniProject };

async function main() {
  const [scenarioName, url] = process.argv.slice(2);
  const scenario = SCENARIOS[scenarioName];
  if (!scenario || !/^http:\/\/127\.0\.0\.1:\d+\//.test(url || "")) {
    throw new ProbeError("usage: browser_probe.mjs <static-page|mini-project> <http://127.0.0.1:PORT/...>", true);
  }
  const executable = findBrowser();
  if (!executable) {
    throw new ProbeError("no Chromium-family browser found (install Edge or Chrome, or set AGENT_LAB_BROWSER)", true);
  }
  const browser = await launch(executable);
  let cdp;
  try {
    cdp = await Cdp.connect(browser.endpoint);
    const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    const page = new Page(cdp, sessionId, new URL(url).origin);
    await page.init();
    const observations = await scenario(page, url);
    observations.load = {
      exceptions: page.exceptions,
      consoleErrors: page.consoleErrors,
      requests: Object.fromEntries(page.requests),
      remote: page.remote,
      dialogs: page.dialogs,
    };
    return { ok: true, browser: basename(executable), observations };
  } finally {
    try {
      await Promise.race([cdp?.send("Browser.close"), sleep(2000)]);
    } catch {
      // The process is killed below either way.
    }
    browser.child.kill();
    await sleep(300);
    try {
      rmSync(browser.profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      // A leftover temp profile is harmless.
    }
  }
}

const watchdog = setTimeout(() => {
  process.stdout.write(JSON.stringify({ ok: false, infrastructure: true, error: "browser probe timed out" }) + "\n");
  process.exit(3);
}, DEADLINE_MS);

main().then((result) => {
  clearTimeout(watchdog);
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exit(0);
}, (error) => {
  clearTimeout(watchdog);
  const infrastructure = error instanceof ProbeError ? error.infrastructure : true;
  process.stdout.write(JSON.stringify({ ok: false, infrastructure, error: String(error.message || error).slice(0, 400) }) + "\n");
  process.exit(infrastructure ? 3 : 4);
});
