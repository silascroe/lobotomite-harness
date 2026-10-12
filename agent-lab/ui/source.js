// Data layer. The console talks to one of two sources with the same interface:
// LiveSource, the local Agent Lab API on this machine, and ShowcaseSource,
// recorded runs bundled as static files for a public, read-only showcase.

export class ShowcaseError extends Error {
  constructor() {
    super("This is a showcase of recorded runs. Nothing here can start work or touch a real machine.");
    this.name = "ShowcaseError";
  }
}

const json = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body ?? {}),
});

function filePath(path) {
  return String(path).split("/").map(encodeURIComponent).join("/");
}

export class LiveSource {
  constructor() {
    this.kind = "live";
    this.readOnly = false;
  }

  async request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, options);
    } catch {
      throw new Error("The local Agent Lab service is not reachable. Start it again and retry.");
    }
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = { error: `The server returned an unreadable response (${response.status}).` };
    }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  health() { return this.request("/api/health"); }
  runs() { return this.request("/api/runs").then((d) => d.runs || []); }
  run(id) { return this.request(`/api/runs/${encodeURIComponent(id)}`); }
  runEvents(id, offset = 0) { return this.request(`/api/runs/${encodeURIComponent(id)}/events?offset=${offset}`); }
  runFile(id, path) { return this.request(`/api/runs/${encodeURIComponent(id)}/file/${filePath(path)}`); }
  sessions() { return this.request("/api/sessions").then((d) => d.sessions || []); }
  session(id) { return this.request(`/api/sessions/${encodeURIComponent(id)}`); }
  sessionFile(id, path) { return this.request(`/api/sessions/${encodeURIComponent(id)}/file/${filePath(path)}`); }
  tasks() { return this.request("/api/tasks").then((d) => d.tasks || []); }
  projects() { return this.request("/api/projects").then((d) => d.projects || []); }
  skills(projectPath = "") {
    const query = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : "";
    return this.request(`/api/skills${query}`);
  }
  provider() { return this.request("/api/provider").then((d) => d.provider); }
  reasoningLevels() { return this.request("/api/reasoning-levels").then((d) => d.levels || []); }

  startRun(payload) { return this.request("/api/runs", json(payload)); }
  stopRun(id) { return this.request(`/api/runs/${encodeURIComponent(id)}/stop`, json({})); }
  resumeRun(id) { return this.request(`/api/runs/${encodeURIComponent(id)}/resume`, json({})); }
  resolveRunApproval(id, decision) { return this.request(`/api/runs/${encodeURIComponent(id)}/approval`, json({ decision })); }

  createSession(payload) { return this.request("/api/sessions", json(payload)); }
  sendMessage(id, content) { return this.request(`/api/sessions/${encodeURIComponent(id)}/messages`, json({ content })); }
  stopJob(id) { return this.request(`/api/sessions/${encodeURIComponent(id)}/stop`, json({})); }
  retryJob(id) { return this.request(`/api/sessions/${encodeURIComponent(id)}/retry`, json({})); }
  resolveJobApproval(id, decision) { return this.request(`/api/sessions/${encodeURIComponent(id)}/approval`, json({ decision })); }
  sessionSettings(id, settings) { return this.request(`/api/sessions/${encodeURIComponent(id)}/settings`, json(settings)); }

  createProject(name) { return this.request("/api/projects", json({ name })); }
  configureProvider(payload) { return this.request("/api/provider", json(payload)); }
  discoverSkills(payload) { return this.request("/api/skills/discover", json(payload)); }
}

export class ShowcaseSource {
  constructor(base = "showcase/") {
    this.kind = "showcase";
    this.readOnly = true;
    this.base = base;
    this.cache = new Map();
  }

  async load(path) {
    if (!this.cache.has(path)) {
      this.cache.set(path, fetch(`${this.base}${path}`).then((r) => {
        if (!r.ok) throw new Error(`Showcase file missing: ${path}`);
        return r.json();
      }));
    }
    return this.cache.get(path);
  }

  manifest() { return this.load("manifest.json"); }
  health() { return this.manifest().then(() => ({ status: "ok", showcase: true })); }
  runs() { return this.manifest().then((m) => m.runs || []); }
  run(id) { return this.load(`runs/${encodeURIComponent(id)}.json`); }
  async runEvents(id) {
    const run = await this.run(id);
    return { offset: 0, next: run.events_full.length, events: run.events_full, complete: true };
  }
  async runFile(id, path) {
    const run = await this.run(id);
    const content = run.file_contents?.[path];
    if (content == null) throw new Error("This file is not included in the showcase recording.");
    return { path, content, truncated: false };
  }
  sessions() { return this.manifest().then((m) => Promise.all((m.sessions || []).map((id) => this.session(id)))); }
  session(id) { return this.load(`sessions/${encodeURIComponent(id)}.json`); }
  async sessionFile() { throw new Error("Chat files are not included in the showcase recording."); }
  tasks() { return this.manifest().then((m) => m.tasks || []); }
  projects() { return Promise.resolve([]); }
  skills() { return this.manifest().then((m) => m.skills || { defaults: [], skills: [] }); }
  provider() { return this.manifest().then((m) => m.provider || { provider: "local", label: "Local model", model: "" }); }
  reasoningLevels() { return this.manifest().then((m) => m.reasoning_levels || []); }

  refuse() { return Promise.reject(new ShowcaseError()); }
  startRun() { return this.refuse(); }
  stopRun() { return this.refuse(); }
  resumeRun() { return this.refuse(); }
  resolveRunApproval() { return this.refuse(); }
  createSession() { return this.refuse(); }
  sendMessage() { return this.refuse(); }
  stopJob() { return this.refuse(); }
  retryJob() { return this.refuse(); }
  resolveJobApproval() { return this.refuse(); }
  sessionSettings() { return this.refuse(); }
  createProject() { return this.refuse(); }
  configureProvider() { return this.refuse(); }
  discoverSkills() { return this.refuse(); }
}

async function reachable(timeoutMs = 2500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("/api/health", { signal: controller.signal });
    if (!response.ok) return false;
    const data = await response.json();
    return data?.status === "ok";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function createSource(location = window.location) {
  const params = new URLSearchParams(location.search);
  const loopback = ["127.0.0.1", "localhost", "[::1]", "::1"].includes(location.hostname);
  // Only the local console has an API; anywhere else is the public showcase.
  if (params.has("showcase") || location.protocol === "file:" || !loopback) return new ShowcaseSource();
  if (await reachable()) return new LiveSource();
  const showcase = new ShowcaseSource();
  try {
    await showcase.manifest();
    return showcase;
  } catch {
    return new LiveSource(); // neither is available; the live source reports the outage clearly
  }
}
