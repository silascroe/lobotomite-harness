// HTML for the instrument views. Every string that came from a model, a file
// or a record goes through esc() before it reaches markup.
import { esc, clock, num, TOOL_LABEL, PHASES } from "./model.js";

const pct = (t, D) => `${Math.max(0, Math.min(100, (t / D) * 100)).toFixed(3)}%`;
const phaseVar = (p) => `var(--ph-${PHASES.includes(p) ? p : "intake"})`;

export function phaseAt(run, at) {
  let current = run.phases[0]?.phase || "intake";
  for (const p of run.phases) if (p.from <= at + 1e-6) current = p.phase;
  return current;
}

export function promptLimit(state) {
  const windowTokens = Number(state?.model_context_tokens) || 0;
  const reserve = Number(state?.reasoning?.max_tokens) || 0;
  return windowTokens && reserve && windowTokens > reserve ? { limit: windowTokens - reserve, windowTokens, reserve } : null;
}

function toolTarget(t) {
  const a = t.args || {};
  if (t.paths?.length) return t.paths.join(", ");
  if (t.action === "run_command") return a.command || "";
  if (t.action === "workflow_checkpoint") return a.phase || "";
  if (t.action === "list_files") return a.path || ".";
  if (t.action === "find_skills") return a.query || "";
  return "";
}

export function turnSummary(run, turn) {
  const bits = turn.tools.map((t) => `${TOOL_LABEL[t.action] || t.action} ${toolTarget(t)}`.trim() + (t.failed ? " ✕" : t.fallback ? " !" : ""));
  const gates = run.gates.filter((g) => g.turn === turn.n);
  if (!bits.length) {
    if (turn.marks.some((m) => m.kind === "invalid")) bits.push(turn.truncated ? "output capped · no valid action" : "no valid action");
    else if (gates.some((g) => g.kind === "refused" || g.kind.startsWith("eval"))) bits.push("asked to finish");
    else if (turn.marks.some((m) => m.kind === "duplicate")) bits.push("repeated an action");
    else bits.push("—");
  }
  return bits.join(" · ");
}

function chipFor(t) {
  const cls = t.failed ? "bad" : t.fallback ? "warn" : "";
  // Plain text: escaped where it is used (title attributes).
  const why = t.failed ? " failed: " + t.error : t.fallback ? " (context matched nothing)" : "";
  const label = "turn " + t.turn + ": " + t.action + (toolTarget(t) ? " " + toolTarget(t) : "") + why;
  return { cls, glyph: t.failed ? "▲" : t.fallback ? "!" : t.glyph, label };
}

/* ---------- horizontal recorder ---------- */

export function horizontalRecorder(run, state, ui) {
  const D = Math.max(1, run.duration);
  const upto = ui.upto ?? D;
  const visibleTurns = run.turns.filter((t) => t.at <= upto + 1e-6);
  const visibleTools = run.tools.filter((t) => t.at <= upto + 1e-6);
  const step = D > 1800 ? 300 : D > 600 ? 120 : D > 240 ? 60 : D > 90 ? 30 : 10;
  const ticks = [];
  for (let s = 0; s <= D + 0.001; s += step) ticks.push(s);
  const grid = `<div class="grid-lines" aria-hidden="true">${ticks.slice(1).map((s) => `<i style="left:${pct(s, D)}"></i>`).join("")}</div>`;
  const ruler = ticks.map((s) => `<span style="left:${pct(s, D)}">${clock(s)}</span>`).join("");

  const phases = run.phases.filter((p) => p.from <= upto).map((p) => {
    const to = Math.min(p.to ?? D, upto);
    return `<div class="ph" style="left:${pct(p.from, D)};width:calc(${pct(Math.max(0, to - p.from), D)} - 2px);background:${phaseVar(p.phase)}" title="${esc(p.phase)} ${clock(p.from)}–${clock(to)}">${esc(p.phase)}</div>`;
  }).join("");

  const maxOut = Math.max(run.maxOutput || 0, ...run.turns.map((t) => t.output), 1);
  const capKnown = Number(state?.reasoning?.max_tokens) > 0;
  const outH = 74;
  const bars = visibleTurns.map((t) => `<div class="bar${t.truncated ? " trunc" : ""}" style="left:${pct(t.at, D)};height:${Math.max(3, Math.round((t.output / maxOut) * outH))}px" title="turn ${t.n}: ${num(t.output)} output tokens${t.truncated ? " (cap)" : ""}"></div>`).join("");
  const truncLabels = visibleTurns.filter((t) => t.truncated).map((t) => `<span class="gate${t.at / D > 0.8 ? " right" : ""}" style="left:${pct(t.at, D)};top:20px;padding-left:10px">T${t.n} hit the cap, no valid action</span>`).join("");

  const limit = promptLimit(state);
  const maxPrompt = Math.max(limit?.limit || 0, ...run.turns.map((t) => t.prompt), 1) * 1.1;
  const pH = 70;
  const pts = visibleTurns.map((t) => `${((t.at / D) * 1000).toFixed(1)},${(pH - (t.prompt / maxPrompt) * pH).toFixed(1)}`).join(" ");
  const limitY = limit ? (pH - (limit.limit / maxPrompt) * pH).toFixed(1) : null;
  const promptLane = `<svg viewBox="0 0 1000 ${pH}" preserveAspectRatio="none" aria-hidden="true">
    ${limitY ? `<line x1="0" x2="1000" y1="${limitY}" y2="${limitY}" stroke="#36434a" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>` : ""}
    <polyline points="${pts}" fill="none" stroke="var(--model)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>
    ${visibleTurns.map((t) => `<circle cx="${((t.at / D) * 1000).toFixed(1)}" cy="${(pH - (t.prompt / maxPrompt) * pH).toFixed(1)}" r="1.6" fill="var(--model)" vector-effect="non-scaling-stroke"/>`).join("")}
  </svg>${limit ? `<span class="cap-label" style="top:${Math.max(0, Number(limitY) - 14)}px">${num(limit.limit)} = ${num(limit.windowTokens)} window − ${num(limit.reserve)} reply</span>` : ""}`;

  // Stack chips into rows so neighbours never overlap.
  const rowsEnd = [];
  const chips = visibleTools.map((t) => {
    const x = (t.at / D) * 100;
    let row = rowsEnd.findIndex((end) => x - end >= 2.1);
    if (row < 0) { row = rowsEnd.length; rowsEnd.push(-99); }
    rowsEnd[row] = x;
    const c = chipFor(t);
    return `<span class="chip ${c.cls}" style="left:${pct(t.at, D)};top:${8 + row * 24}px" title="${esc(c.label)}" aria-hidden="true">${esc(c.glyph)}</span>`;
  }).join("");
  const toolH = 16 + Math.max(1, rowsEnd.length) * 24;

  const kept = run.context.filter((c) => c.at <= upto);
  const cH = 30;
  let path = `M0,0`;
  let last = 1;
  for (const c of kept) {
    const x = ((c.at / D) * 1000).toFixed(1);
    path += ` L${x},${((1 - last) * cH).toFixed(1)} L${x},${((1 - c.kept) * cH).toFixed(1)}`;
    last = c.kept;
  }
  path += ` L${((Math.min(upto, D) / D) * 1000).toFixed(1)},${((1 - last) * cH).toFixed(1)}`;
  const finalKept = kept.length ? kept[kept.length - 1].kept : 1;
  const contextLane = `<svg viewBox="0 0 1000 ${cH}" preserveAspectRatio="none" aria-hidden="true"><path d="${path} L${((Math.min(upto, D) / D) * 1000).toFixed(1)},${cH} L0,${cH} Z" fill="#26343a"/><path d="${path}" fill="none" stroke="#4f6670" vector-effect="non-scaling-stroke"/></svg>`;

  const gateEnd = [-99, -99];
  const gates = run.gates.filter((g) => g.at <= upto && g.kind !== "invalid").map((g) => {
    const x = (g.at / D) * 100;
    const right = x > 82;
    let row = gateEnd.findIndex((end) => x - end >= 14);
    if (row < 0) row = 1;
    gateEnd[row] = x;
    const ok = g.kind === "eval-pass";
    return `<span class="gate${ok ? " ok" : ""}${right ? " right" : ""}" style="left:${pct(g.at, D)};top:${6 + row * 20}px" title="${esc(g.detail || g.label)}">◆ ${esc(g.label)}</span>`;
  }).join("");

  const rep = run.repair && run.repair.start <= upto
    ? `<div class="repair-band" style="left:${pct(run.repair.start, D)};width:${pct(Math.min(run.repair.end ?? upto, upto) - run.repair.start, D)}"><span>REPAIR · ${num(run.repair.extension_turns_used ?? 0)} of ${num(run.repair.extension_limit ?? 6)} extra calls</span></div>`
    : "";
  const unplayed = upto < D - 0.01 ? `<div class="unplayed" style="left:${pct(upto, D)}"></div><div class="cursor" style="left:${pct(upto, D)}"></div>` : "";
  const hits = run.turns.map((t, i) => {
    const end = run.turns[i + 1]?.at ?? D;
    const disabled = t.at > upto + 1e-6;
    return `<button type="button" id="hit-${t.n}" data-turn="${t.n}" aria-pressed="${ui.turn === t.n}" title="T${t.n} · ${esc(turnSummary(run, t))}" aria-label="Turn ${t.n} at ${clock(t.at)}: ${esc(turnSummary(run, t))}" ${disabled ? "disabled" : ""} style="left:${pct(t.at, D)};width:${pct(Math.max(0.5, end - t.at), D)}"></button>`;
  }).join("");

  const overlay = `<div class="overlay">${rep}${unplayed}</div><div class="hits">${hits}</div>`;
  const lanes = [
    ["", 22, `<div class="lane ruler" aria-hidden="true">${ruler}</div>`],
    ["PHASE", 34, `<div class="lane" style="height:34px">${grid}${phases}</div>`],
    [`MODEL OUT<small>tokens</small>`, outH + 12, `<div class="lane" style="height:${outH + 12}px">${grid}<div class="cap-line" style="top:12px"></div><span class="cap-label" style="top:12px">${num(maxOut)} ${capKnown ? "cap" : "peak"}</span>${bars}${truncLabels}</div>`],
    [`PROMPT<small>tokens in</small>`, pH, `<div class="lane" style="height:${pH}px">${grid}${promptLane}</div>`],
    ["TOOLS", toolH, `<div class="lane" style="height:${toolH}px">${grid}${chips}</div>`],
    [`CONTEXT<small>${Math.round(finalKept * 100)}% kept</small>`, cH + 10, `<div class="lane" style="height:${cH + 10}px;padding-top:5px">${grid}<div style="position:relative;height:${cH}px">${contextLane}</div></div>`],
    ["GATES", 70, `<div class="lane" style="height:70px;border-bottom:1px solid var(--line)">${grid}${gates}</div>`],
  ];
  return `<div class="tape-h"><div class="lanes">
    <div class="lane-labels">${lanes.map(([label, h], i) => `<div class="lane-label" style="height:${h}px${i === 0 ? ";border-top:0" : ""}">${label}</div>`).join("")}</div>
    <div class="lane-stack">${lanes.map(([, , lane]) => lane).join("")}${overlay}</div>
  </div>
  <div class="legend h"><span>L list</span><span>R read</span><span>W write</span><span>E replace</span><span>P patch</span><span>$ run</span><span>Δ diff</span><span>C checkpoint</span><span class="amber">▲ failed</span><span class="amber">! accepted on a context miss</span><span>click a column to open the turn</span></div></div>`;
}

/* ---------- overview strip (phones) ---------- */

export function overviewStrip(run, ui) {
  const D = Math.max(1, run.duration);
  const upto = ui.upto ?? D;
  const maxOut = Math.max(run.maxOutput || 0, ...run.turns.map((t) => t.output), 1);
  const bars = run.turns.filter((t) => t.at <= upto).map((t) => `<div class="bar${t.truncated ? " trunc" : ""}" style="left:${pct(t.at, D)};height:${Math.max(2, Math.round((t.output / maxOut) * 34))}px"></div>`).join("");
  const fails = run.tools.filter((t) => (t.failed || t.fallback) && t.at <= upto).map((t) => `<i style="position:absolute;top:2px;left:${pct(t.at, D)};width:6px;height:6px;margin-left:-3px;background:var(--amber);transform:rotate(45deg)"></i>`).join("");
  const rep = run.repair && run.repair.start <= upto ? `<div class="repair-band" style="left:${pct(run.repair.start, D)};width:${pct(Math.min(run.repair.end ?? upto, upto) - run.repair.start, D)}"></div>` : "";
  const cursor = upto < D - 0.01 ? `<div class="cursor" style="left:${pct(upto, D)}"></div>` : "";
  return `<div class="overview" aria-hidden="true">${rep}${bars}${fails}${cursor}</div>`;
}

/* ---------- vertical tape (phones) ---------- */

export function verticalTape(run, state, ui, detailHtml) {
  const D = Math.max(1, run.duration);
  const upto = ui.upto ?? D;
  const maxOut = Math.max(run.maxOutput || 0, ...run.turns.map((t) => t.output), 1);
  const rows = [];
  let repairOpened = false;
  for (const t of run.turns) {
    if (t.at > upto + 1e-6) break;
    const inRepair = run.repair && t.at >= run.repair.start - 0.5 && (run.repair.end == null || t.at <= run.repair.end + 0.5);
    if (inRepair && !repairOpened) {
      repairOpened = true;
      rows.push(`<div class="repair-edge">REPAIR EPISODE · up to ${num(run.repair.extension_limit ?? 6)} extra calls</div>`);
    }
    const phase = phaseAt(run, t.at);
    const glyphs = t.tools.map((tool) => {
      const c = chipFor(tool);
      return `<span class="chip ${c.cls}" aria-hidden="true">${esc(c.glyph)}</span>`;
    }).join("");
    const sel = ui.turn === t.n;
    rows.push(`<div class="trow${sel ? " sel" : ""}${inRepair ? " in-repair" : ""}">
      <div class="phase-strip" style="background:${phaseVar(phase)}" title="${esc(phase)}"></div>
      <button type="button" class="tmain" id="tape-${t.n}" data-turn="${t.n}" aria-expanded="${sel}">
        <span class="tnum">${t.n}<small>${clock(t.at)}</small></span>
        <span class="tmid"><span class="what">${esc(turnSummary(run, t))}</span><span class="meter"><i class="${t.truncated ? "trunc" : ""}" style="width:${((t.output / maxOut) * 100).toFixed(1)}%"></i></span></span>
        <span class="tglyphs">${glyphs}</span>
      </button>
      ${sel ? `<div class="tdetail">${detailHtml}</div>` : ""}
    </div>`);
    for (const g of run.gates.filter((x) => x.turn === t.n && x.kind !== "invalid" && x.at <= upto)) {
      rows.push(`<div class="gate-row${g.kind === "eval-pass" ? " ok" : ""}">◆ ${esc(g.label)}${g.detail && g.kind !== "refused" ? ` · ${esc(g.detail.slice(0, 120))}` : ""}</div>`);
    }
  }
  if (run.repair && run.repair.end != null && run.repair.end <= upto) {
    rows.push(`<div class="repair-edge">REPAIR ${esc(String(run.repair.status || "").replace(/_/g, " ").toUpperCase())} · ${num(run.repair.extension_turns_used ?? 0)} of ${num(run.repair.extension_limit ?? 6)} used</div>`);
  }
  return `<div class="tape-v">${overviewStrip(run, ui)}${rows.join("") || '<div class="empty">No turns recorded yet.</div>'}</div>`;
}

/* ---------- turn detail ---------- */

function prettyAction(content) {
  try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; }
}

function patchHtml(patch, highlight = []) {
  const marks = new Set(highlight);
  return String(patch || "").split("\n").map((line) => {
    const body = line.startsWith(" ") || line.startsWith("+") || line.startsWith("-") ? line.slice(1) : line;
    const cls = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "";
    const inner = marks.has(body) && !cls ? `<mark>${esc(line)}</mark>` : esc(line);
    return cls ? `<span class="${cls}">${inner}</span>` : inner;
  }).join("\n");
}

function excerpt(text, lines = 40) {
  const all = String(text ?? "").split("\n");
  return all.length > lines ? `${all.slice(0, lines).join("\n")}\n… ${all.length - lines} more lines` : all.join("\n");
}

export function toolHtml(t) {
  const a = t.args || {};
  const r = t.result || {};
  let body = "";
  if (t.action === "apply_patch") body = `<pre class="code">${patchHtml(a.patch, t.fallback ? t.fallback.misses.flatMap((m) => m.missing) : [])}</pre>`;
  else if (t.action === "write_file") body = `<pre class="code">${esc(excerpt(a.content))}</pre>`;
  else if (t.action === "replace_text") body = `<div class="compare" style="margin-top:12px"><div><div class="label">old text</div><pre class="code">${esc(excerpt(a.old_text, 20))}</pre></div><div><div class="label">new text</div><pre class="code">${esc(excerpt(a.new_text, 20))}</pre></div></div>`;
  else if (t.action === "read_file" && typeof r.content === "string") body = `<pre class="code">${esc(excerpt(r.content))}</pre>`;
  else if (t.action === "run_command") body = `<pre class="code wrap">$ ${esc(a.command || "")}${r.stdout ? `\n${esc(excerpt(r.stdout, 20))}` : ""}${r.stderr ? `\n${esc(excerpt(r.stderr, 20))}` : ""}</pre>`;
  else if (t.action === "workflow_checkpoint") body = `<pre class="code wrap">${esc(a.phase || "")}: ${esc(a.summary || "")}${a.next_action ? `\nnext: ${esc(a.next_action)}` : ""}</pre>`;
  else if (t.action === "list_files") body = `<pre class="code">${esc((r.entries || []).map((e) => (typeof e === "string" ? e : e.path || e.name || JSON.stringify(e))).join("\n") || "(empty)")}</pre>`;
  else if (t.action === "git_diff") body = r.diff ? `<pre class="code">${patchHtml(excerpt(r.diff, 60))}</pre>` : "";
  const result = t.failed
    ? `<p class="result-line bad">▲ ${esc(t.error)}</p>`
    : `<p class="result-line ok">✓ ${t.action === "run_command" ? `exit ${esc(r.exit_code ?? 0)}` : "ok"}${r.bytes != null ? ` · ${num(r.bytes)} bytes` : ""}${r.changed ? ` · changed ${esc([].concat(r.changed).join(", "))}` : ""}</p>`;
  const fb = t.fallback
    ? `<div class="callout"><h4>Accepted on a context miss</h4><p>The harness reported success, but the patch's context matched nothing in ${esc(t.fallback.path)}${t.fallback.beforeTurn ? ` as the model last saw it (${esc(t.fallback.beforeKind)} at turn ${t.fallback.beforeTurn})` : ""}. Its added lines were inserted by the <span class="mono">@@</span> line number${t.fallback.misses[0]?.insertedAt ? ` (line ${t.fallback.misses[0].insertedAt})` : ""} instead of being rejected. ${t.fallback.misses.some((m) => m.missing.length) ? "Quoted lines that are not in the file are highlighted." : "Every quoted line exists in the file, just not in that order."}</p></div>`
    : "";
  return `<div class="section-label">${esc(t.action)}${toolTarget(t) ? ` · <span style="text-transform:none">${esc(toolTarget(t))}</span>` : ""}</div>${result}${fb}${body}`;
}

export function turnDetail(run, state, n, { compact = false } = {}) {
  const t = run.turns.find((x) => x.n === n);
  if (!t) return `<div class="empty"><h2>Pick a turn</h2><p>Tap a turn on the tape to see what the model sent and what came back.</p></div>`;
  const i = run.turns.indexOf(t);
  const dur = (t.end ?? run.duration) - t.at;
  const gates = run.gates.filter((g) => g.turn === n);
  const content = t.content ? (t.tools.length ? `<details class="fold" style="margin-top:14px"><summary>raw model reply</summary><pre class="code wrap">${esc(excerpt(prettyAction(t.content), 80))}</pre></details>` : `<div class="section-label">model reply</div><pre class="code wrap">${esc(excerpt(prettyAction(t.content), 60))}</pre>`) : "";
  const gateHtml = gates.map((g) => `<div class="callout"${g.kind === "eval-pass" ? ' style="border-color:var(--model-2);background:transparent"' : ""}><h4${g.kind === "eval-pass" ? ' style="color:var(--model)"' : ""}>◆ ${esc(g.label)}</h4>${g.detail ? `<p>${esc(g.detail)}</p>` : ""}</div>`).join("");
  const invalid = t.marks.filter((m) => m.kind === "invalid").map((m) => `<p class="result-line bad">▲ ${t.truncated ? `output hit the ${num(t.output)}-token cap; ` : ""}${esc(m.error)}</p>`).join("");
  return `${compact ? "" : `<div class="turn-head"><h2>Turn ${t.n} · ${clock(t.at)}</h2><div class="nav-turn">
      <button type="button" class="btn icon" data-act="turn-step" data-step="-1" aria-label="Previous turn" ${i === 0 ? "disabled" : ""}>${ICON.left}</button>
      <button type="button" class="btn icon" data-act="turn-step" data-step="1" aria-label="Next turn" ${i === run.turns.length - 1 ? "disabled" : ""}>${ICON.right}</button></div></div>`}
    <dl class="kv"><div><dt>prompt in</dt><dd>${num(t.prompt)} tok</dd></div><div><dt>output</dt><dd class="${t.truncated ? "amber" : ""}">${num(t.output)} tok${t.truncated ? " · cap" : ""}</dd></div><div><dt>took</dt><dd>${dur >= 0.05 ? `${dur.toFixed(dur < 10 ? 1 : 0)} s` : "–"}</dd></div><div><dt>phase</dt><dd>${esc(phaseAt(run, t.at))}</dd></div></dl>
    ${invalid}${t.tools.map(toolHtml).join("")}${gateHtml}${content}`;
}

/* ---------- process ---------- */

const VALVE = `<svg width="64" height="44" viewBox="0 0 64 44" aria-hidden="true"><path d="M4 6 L32 22 L4 38 Z M60 6 L32 22 L60 38 Z"/></svg>`;

export function processView(proc) {
  const units = proc.units.map((u) => `<div class="unit ${u.kind}"><div class="box">${u.kind.includes("valve") ? VALVE : esc(u.tag)}</div><span class="name">${esc(u.name)}</span><span class="note">${esc(u.note)}</span></div>`).join("");
  const rec = proc.repair
    ? `<div class="recycle${proc.repair.status === "passed" ? " idle" : ""}"><span>REPAIR RECYCLE · ${num(proc.repair.used)} / ${num(proc.repair.limit)} EXTRA CALLS · ${esc(String(proc.repair.status).replace(/_/g, " ").toUpperCase())}</span></div>
       <p class="recycle-note amber mono" style="font-size:12px;margin:10px 0 0">↺ REPAIR RECYCLE: evaluator → implement · ${num(proc.repair.used)} / ${num(proc.repair.limit)} extra calls · ${esc(String(proc.repair.status).replace(/_/g, " "))}</p>`
    : `<div class="recycle idle"><span>REPAIR RECYCLE · NOT USED</span></div>`;
  return `<div class="process"><div style="overflow-x:auto"><div class="pipe">${units}</div>${rec}</div></div>`;
}

export function alarmList(alarms, { limit = 0 } = {}) {
  const list = limit ? alarms.filter((a) => a.state !== "RTN").slice(0, limit) : alarms;
  if (!list.length) return `<p class="dim" style="margin:0">No alarms. Nothing abnormal was recorded.</p>`;
  return `<ul class="alarm-list">${list.map((a) => `<li><span class="pri pri-${a.pri}" aria-label="priority ${a.pri}">${a.pri}</span><span class="t">${clock(a.at)}</span>
    <a class="goto" href="#" data-turn="${a.turn ?? ""}" ${a.turn ? "" : 'aria-disabled="true"'}><span class="tag">${esc(a.tag)}</span><span class="txt">${esc(a.text)}</span></a>
    <span class="st st-${a.state}">${a.state}</span></li>`).join("")}</ul>`;
}

export function gaugeList(run, state) {
  const calls = Number(state.model_calls) || run.turns.length;
  const maxTurns = Number(state.max_turns) || 0;
  const ext = Number(run.repair?.extension_limit) || 0;
  const budget = maxTurns + (run.repair ? ext : 0);
  const last = run.turns[run.turns.length - 1];
  const limit = promptLimit(state);
  const failedTools = run.tools.filter((t) => t.failed).length;
  const g = (label, value, frac, lim, note, alarm) => `<div class="gauge"><div class="row"><span>${label}</span><span>${value}</span></div><div class="track"><div class="fill${alarm ? " alarm" : ""}" style="width:${Math.min(100, Math.max(0, frac * 100)).toFixed(1)}%"></div>${lim != null ? `<div class="limit" style="left:${(lim * 100).toFixed(1)}%"></div>` : ""}</div><div class="note">${note}</div></div>`;
  const scale = (limit?.limit || 6000) * 1.15;
  return `<div class="gauges">
    ${budget ? g("model calls", `${num(calls)} / ${num(budget)}`, calls / budget, maxTurns && ext && run.repair ? maxTurns / budget : null, `${num(maxTurns)} turns${run.repair ? ` + ${num(ext)} repair extension` : ""}`, calls >= budget) : ""}
    ${last ? g("prompt, last turn", `${num(last.prompt)} tok`, last.prompt / scale, limit ? limit.limit / scale : null, limit ? `limit ${num(limit.limit)} · compacted ${num(run.compactions)}×` : `compacted ${num(run.compactions)}×`, limit && last.prompt > limit.limit) : ""}
    ${last ? g("output, last turn", `${num(last.output)} tok`, last.output / Math.max(1, run.maxOutput), null, `cap ${num(run.maxOutput)}${run.turns.some((t) => t.truncated) ? ` · hit at T${run.turns.filter((t) => t.truncated).map((t) => t.n).join(", T")}` : ""}`, last.truncated) : ""}
    ${g("tool calls", num(run.tools.length), run.tools.length ? 1 - failedTools / run.tools.length : 0, null, failedTools ? `${failedTools} failed` : "none failed", false)}
    ${g("wall time", clock(run.duration), run.duration / 600, null, "matrix timeout is 600 s", false)}
  </div>`;
}

/* ---------- file lens ---------- */

const CELL_TITLE = { W: "wrote the whole file", R: "read", E: "replaced text", P: "patched", "P!": "patch accepted though its context matched nothing", X: "edit rejected", "−": "deleted" };

export function fileLens(run, ui) {
  const files = [...run.files.keys()];
  if (!files.length) return `<div class="empty"><h2>No file activity</h2><p>This run never read or changed a file.</p></div>`;
  const turns = run.turns.map((t) => t.n);
  const repair = (n) => run.repair && run.turns.find((t) => t.n === n)?.at >= run.repair.start - 0.5;
  const fileIndex = new Map(files.map((f, i) => [f, i]));
  const cellAt = (file, n, axis = "h") => {
    const evs = run.files.get(file).filter((e) => e.turn === n);
    if (!evs.length) return `<div class="cell" aria-hidden="true"></div>`;
    const e = evs[evs.length - 1];
    const sel = ui.file === file && ui.turn === n;
    return `<button type="button" id="cell-${axis}-${fileIndex.get(file)}-${n}" class="cell ${esc(e.kind)}${sel ? " sel" : ""}" data-file="${esc(file)}" data-turn="${n}" title="turn ${n}: ${esc(CELL_TITLE[e.kind] || e.kind)}" aria-label="${esc(file)}, turn ${n}: ${esc(CELL_TITLE[e.kind] || e.kind)}">${e.kind === "X" ? "✕" : esc(e.kind)}</button>`;
  };
  const keptAt = (n) => {
    let kept = 1;
    for (const c of run.context) if (c.turn <= n) kept = c.kept;
    return kept;
  };
  const h = `<div class="score score-h"><div class="score-grid" style="grid-template-columns:150px repeat(${turns.length}, minmax(26px, 1fr))">
    <div class="tn" style="text-align:left">turn</div>${turns.map((n) => `<div class="tn${repair(n) ? " rep" : ""}">${n}</div>`).join("")}
    ${files.map((f) => `<div class="fname" title="${esc(f)}">${esc(f)}</div>${turns.map((n) => cellAt(f, n)).join("")}`).join("")}
    <div class="tn" style="text-align:left;padding-top:8px">context kept</div>${turns.map((n) => `<div class="kept" title="turn ${n}: ${Math.round(keptAt(n) * 100)}% of the conversation kept"><i style="height:${Math.round(keptAt(n) * 100)}%"></i></div>`).join("")}
  </div></div>`;
  const v = `<div class="score score-v"><div class="score-grid" style="grid-template-columns:44px repeat(${files.length}, minmax(0, 1fr)) 40px">
    <div class="tn">turn</div>${files.map((f) => `<div class="tn" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(f)}">${esc(f)}</div>`).join("")}<div class="tn">ctx</div>
    ${turns.map((n) => `<div class="tn${repair(n) ? " rep" : ""}">${n}</div>${files.map((f) => cellAt(f, n, "v")).join("")}<div class="kept"><i style="height:${Math.round(keptAt(n) * 100)}%"></i></div>`).join("")}
  </div></div>`;
  return `${h}${v}<div class="score-legend"><span><b>W</b> wrote whole file</span><span><b class="cyan">R</b> read</span><span><b>E</b> replaced text</span><span><b>P</b> patched</span><span><b class="amber">P!</b> patch accepted on a context miss</span><span><b class="amber">✕</b> edit rejected</span><span>bar = share of the conversation still in context</span></div>`;
}

export function fileEventDetail(run, file, n) {
  const evs = (run.files.get(file) || []).filter((e) => e.turn === n);
  if (!evs.length) return `<div class="empty"><h2>Pick a cell</h2><p>Each cell is something the model did to a file on one turn.</p></div>`;
  const e = evs[evs.length - 1];
  const t = e.tool;
  let compare = "";
  if (t.fallback && t.fallback.before != null) {
    const missing = new Set(t.fallback.misses.flatMap((m) => m.missing));
    const quoted = String(t.args.patch || "").split("\n").filter((l) => l.startsWith(" ") || (!/^[+\-@*\\]/.test(l) && l.trim())).map((l) => (l.startsWith(" ") ? l.slice(1) : l)).slice(0, 14);
    compare = `<div class="compare" style="margin-top:14px">
      <div><div class="label">patch context (model)</div><pre class="code">${quoted.map((l) => (missing.has(l) ? `<mark>${esc(l)}</mark>` : esc(l))).join("\n")}</pre></div>
      <div><div class="label">on disk (${esc(t.fallback.beforeKind)} at turn ${esc(t.fallback.beforeTurn)})</div><pre class="code">${esc(excerpt(t.fallback.before, 14))}</pre></div></div>`;
  }
  return `<div class="turn-head"><h2>${esc(file)} · turn ${n}</h2><button type="button" class="btn small" data-act="open-file" data-file="${esc(file)}">Current file</button></div>${toolHtml(t)}${compare}`;
}

/* ---------- icons ---------- */

export const ICON = {
  left: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`,
  right: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`,
  play: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>`,
  pause: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h3v11H4zm5 0h3v11H9z" fill="currentColor"/></svg>`,
  close: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 3.5 9 9m0-9-9 9" stroke="currentColor" stroke-width="1.6"/></svg>`,
};
