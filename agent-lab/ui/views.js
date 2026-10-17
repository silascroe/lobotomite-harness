// Page renderers. Each returns an HTML string; app.js owns state and events.
import { esc, clock, num, taskTitle, LEVEL_LABEL, FAILURE_CODES, failureLabel, verdict as verdictOf, chatGroups, chatTitle } from "./model.js";
import { horizontalRecorder, verticalTape, turnDetail, processView, alarmList, gaugeList, fileLens, fileEventDetail, ICON } from "./recorder.js";

const pctText = (x) => `${Math.round(x * 100)}%`;

function ago(seconds) {
  const s = Date.now() / 1000 - Number(seconds || 0);
  if (!seconds || s < 0) return "";
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function runChip(row) {
  const evaluated = row.first_pass_passed != null || Boolean(row.task_profile?.gates?.evaluator);
  const v = verdictOf({ status: row.status, summary: { first_pass_passed: row.first_pass_passed, summary: row.summary, evaluation: evaluated ? { configured: true } : null } });
  const word = v.key === "repaired" ? "REPAIRED" : v.word;
  const cls = v.key === "passed" || v.key === "finished" ? "ok" : v.key === "repaired" ? "rep" : v.key === "running" ? "live" : v.tone === "bad" ? "bad" : "warn";
  return `<span class="vchip ${cls}"><i aria-hidden="true"></i>${esc(word)}</span>`;
}

/* ---------- bench ---------- */

export function benchView(bench, ctx) {
  const done = bench.experiments.filter((e) => e.status !== "planned" && e.n);
  const planned = bench.experiments.filter((e) => e.status === "planned");
  if (!done.length) {
    return `<div class="page-head"><div><div class="eyebrow">bench</div><h1>No benchmark batches yet</h1>
      <p class="lede">Run <span class="mono">agent-lab/benchmarks/catalog_matrix.py</span> to record a matrix. Batches appear here, grouped by <span class="mono">benchmarks/experiments.json</span>.</p></div></div>`;
  }
  const ref = done.find((e) => e.reference) || done[0];
  const sel = done.find((e) => e.id === ctx.experiment) || ref;
  const shape = `${ref.tasks.length} tasks × ${ref.levels.length} reasoning levels × ${ref.batchCount} batches`;
  const half = ref.n ? ((ref.ci[1] - ref.ci[0]) / 2) * 100 : 0;
  const ticks = [0, 25, 50, 75, 100];
  const scale = (e) => {
    if (!e.n) return `<div class="scale" aria-hidden="true"><div class="planned-line"></div></div>`;
    const p = e.k / e.n;
    return `<div class="scale${e === ref ? " ref" : ""}" role="img" aria-label="${esc(e.title)}: ${pctText(p)}, 95% interval ${pctText(e.ci[0])} to ${pctText(e.ci[1])}">
      <div class="axis"></div>${ticks.map((t) => `<div class="tick" style="left:${t}%"></div>`).join("")}
      ${e !== ref ? `<div class="refline" style="left:${((ref.k / ref.n) * 100).toFixed(2)}%"></div>` : ""}
      <div class="ci" style="left:${(e.ci[0] * 100).toFixed(2)}%;width:${((e.ci[1] - e.ci[0]) * 100).toFixed(2)}%"></div>
      <div class="pt" style="left:${(p * 100).toFixed(2)}%"></div></div>`;
  };
  const row = (e) => {
    const cmp = e.comparison ? `${e.comparison.delta >= 0 ? "+" : "−"}${Math.abs(e.comparison.delta)} vs ${esc(e.comparison.refTitle.toLowerCase())} · p = ${e.comparison.p.toFixed(2)}` : e === ref ? "reference" : "";
    const meta = e.status === "planned" ? esc(e.note || "planned") : `${num(e.n)} runs · ${esc(e.checkers || "")}${e.loose ? " · not in experiments.json" : ""}`;
    return `<div class="forest-row${e.status === "planned" ? " planned" : ""}">
      <div class="who"><b>${esc(e.title)}</b><small>${meta}</small></div>
      ${scale(e)}
      <div class="score-num">${e.n ? `${num(e.k)}/${num(e.n)}<small>${pctText(e.k / e.n)}${cmp ? ` · ${cmp}` : ""}</small>` : "not run"}</div></div>`;
  };
  const tabs = done.length > 1 ? `<nav class="tabs" aria-label="Experiments">${done.map((e) => `<a href="#/bench?x=${encodeURIComponent(e.id)}" aria-current="${e === sel ? "page" : "false"}">${esc(e.title)}</a>`).join("")}</nav>` : "";
  return `<div class="page-head"><div><div class="eyebrow">bench · ${esc(bench.model || ref.model || "")}</div><h1>${esc(bench.question || "Benchmark experiments")}</h1>
    <p class="lede">Every experiment is the same ${esc(shape)}, graded by checkers that load and use the result. Only the harness changes between rows.</p></div></div>
  <section class="panel" aria-label="Pass rate by experiment">
    <div class="panel-head"><h2>pass rate · 95% interval</h2><span class="mono dim" style="font-size:12px">dashed line = ${esc(ref.title.toLowerCase())}</span></div>
    <div class="panel-body"><div class="forest">
      <div class="forest-row forest-head" style="padding:0;border:0"><div></div><div class="axis-labels">${ticks.map((t) => `<span style="left:${t}%">${t}%</span>`).join("")}</div><div></div></div>
      ${done.map(row).join("")}${planned.map(row).join("")}
    </div>
    <p class="statline" style="margin-top:10px">Intervals are Wilson 95%; comparisons are two-sided Fisher exact. At ${num(ref.n)} runs an arm the interval is about ±${Math.round(half)} points, so only large effects can show.</p></div>
  </section>
  <div class="exp-tabs">${tabs}${matrixPanel(sel, ref, ctx)}</div>`;
}

function matrixPanel(e, ref, ctx) {
  const cell = (c) => {
    const title = c.code === "none" ? "no run" : `${taskTitle(c.task)} · ${LEVEL_LABEL[c.reasoning_level] || c.reasoning_level} · batch ${c.batch + 1}: ${c.code === "pass" ? "passed first try" : c.code === "repaired" ? "passed after repair" : failureLabel(c.code)}`;
    const cls = c.code === "none" ? "none" : c.code === "pass" ? "pass" : c.code === "repaired" ? "repaired" : "fail";
    const label = cls === "fail" ? esc(c.code) : "";
    if (c.run_id && ctx.linkable(c)) return `<a class="mcell ${cls}" href="#/runs/${encodeURIComponent(c.run_id)}" title="${esc(title)}" aria-label="${esc(title)}">${label}</a>`;
    return `<span class="mcell ${cls}${c.run_id ? " dead" : ""}" title="${esc(title)}${c.run_id ? " (record not available here)" : ""}" role="img" aria-label="${esc(title)}">${label}</span>`;
  };
  const head = `<thead><tr><th></th>${e.levels.map((l) => `<th class="grp" colspan="${e.batchCount}">${esc(LEVEL_LABEL[l] || l)}</th>`).join('<th class="gap"></th>')}<th>pass</th></tr></thead>`;
  const rows = e.rows.map((r) => {
    const groups = e.levels.map((_, li) => r.cells.slice(li * e.batchCount, (li + 1) * e.batchCount).map((c) => `<td>${cell(c)}</td>`).join(""));
    const other = ref !== e ? ref.rows.find((x) => x.task === r.task) : null;
    return `<tr class="mrow"><th class="task" scope="row">${esc(r.title)}</th>${groups.join('<td class="gap"></td>')}<td class="tot">${r.k}/${r.n}${other ? ` <small>· ${other.k}/${other.n}</small>` : ""}</td></tr>`;
  }).join("");
  const causeBar = (x, title) => {
    const entries = Object.entries(x.causes).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((s, [, v]) => s + v, 0);
    if (!total) return "";
    const colors = { E: ["var(--amber)", "var(--amber-ink)"], R: ["#b8823a", "#0e1113"], D: ["#8a5a1f", "var(--ink)"], T: ["#4f6670", "var(--ink)"], W: ["#3a4a52", "var(--ink)"], G: ["#3a4a52", "var(--ink)"], F: ["#5a3a2a", "var(--ink)"], B: ["#2f3b41", "var(--ink)"], O: ["#2f3b41", "var(--ink)"], "?": ["#2f3b41", "var(--ink)"] };
    return `<div><h3 class="eyebrow" style="margin:0 0 10px">${esc(title)} · ${total} failed</h3>
      <div class="stack" role="img" aria-label="${esc(entries.map(([k, v]) => `${v} ${failureLabel(k)}`).join(", "))}">${entries.map(([k, v]) => `<div style="flex:${v} 1 0;background:${colors[k]?.[0] || "#2f3b41"};color:${colors[k]?.[1] || "var(--ink)"}">${esc(k)} ${v}</div>`).join("")}</div>
      <div class="stack-legend">${entries.map(([k, v]) => `<span><b>${esc(k)}</b> ${v} ${esc(failureLabel(k))}</span>`).join("")}</div></div>`;
  };
  return `<section class="panel" aria-label="${esc(e.title)} matrix">
    <div class="panel-head"><h2>${esc(e.title)} · every run</h2><span class="mono dim" style="font-size:12px">${esc(e.resolved.map((b) => b.batch_id.replace(/^matrix-/, "")).join(" · "))}</span></div>
    <div class="panel-body">
      <p class="matrix-key mono dim" style="font-size:12px;margin:0 0 6px;gap:12px;flex-wrap:wrap">${e.levels.map((l) => esc(LEVEL_LABEL[l] || l)).join(" · ")} · ${e.batchCount} batches each${ref !== e ? ` · right: ${esc(ref.title.toLowerCase())}` : ""}</p>
      <div class="matrix"><table>${head}<tbody>${rows}</tbody></table></div>
      <div class="statline"><span>first-try passes <b>${num(e.firstPass)}</b></span><span>passed after repair <b>${num(e.repaired)}</b></span><span>repair episodes that passed <b>${num(e.repairEpisodes.passed)}/${num(e.repairEpisodes.total)}</b></span><span>mean model calls <b>${e.meanCalls.toFixed(1)}</b></span><span>mean wall time <b>${clock(e.meanSeconds)}</b></span></div>
      <div class="stack-legend" style="margin-top:14px"><span><span class="mcell pass" style="display:inline-flex;width:14px;height:14px;vertical-align:-2px"></span> passed first try</span><span><span class="mcell repaired" style="display:inline-flex;width:14px;height:14px;vertical-align:-2px"></span> passed after repair</span>${Object.entries(FAILURE_CODES).filter(([k]) => e.causes[k] || ref.causes[k]).map(([k, v]) => `<span><b class="amber">${esc(k)}</b> ${esc(v)}</span>`).join("")}</div>
      <div class="causes">${causeBar(e, e.title)}${ref !== e ? causeBar(ref, ref.title) : ""}</div>
    </div></section>`;
}

/* ---------- runs ---------- */

export function runsView(runs, ui, readOnly) {
  const q = (ui.query || "").toLowerCase();
  const pick = ui.filter || "all";
  const status = (r) => (r.status === "success" || r.status === "complete" ? "passed" : r.status === "running" || r.status === "waiting_approval" ? "live" : "stopped");
  const shown = runs.filter((r) => (pick === "all" || status(r) === pick) && (!q || `${r.run_id} ${taskTitle(r.task_profile)} ${r.summary || ""} ${r.reasoning_level || ""}`.toLowerCase().includes(q)));
  const counts = { all: runs.length, passed: 0, stopped: 0, live: 0 };
  for (const r of runs) counts[status(r)] += 1;
  const filters = ["all", "passed", "stopped", "live"].map((f) => `<button type="button" data-act="filter" data-filter="${f}" aria-pressed="${pick === f}">${f} ${counts[f]}</button>`).join("");
  const rows = shown.map((r) => `<tr>
      <td><a href="#/runs/${encodeURIComponent(r.run_id)}">${runChip(r)}</a></td>
      <td><a href="#/runs/${encodeURIComponent(r.run_id)}"><b style="font-weight:600">${esc(taskTitle(r.task_profile))}</b><div class="rid">${esc(r.run_id)}</div></a></td>
      <td><a href="#/runs/${encodeURIComponent(r.run_id)}" class="mono">${esc(LEVEL_LABEL[r.reasoning_level] || r.reasoning_level || "–")}</a></td>
      <td class="num"><a href="#/runs/${encodeURIComponent(r.run_id)}">${num(r.model_calls)}</a></td>
      <td class="num"><a href="#/runs/${encodeURIComponent(r.run_id)}">${r.elapsed_seconds != null ? clock(r.elapsed_seconds) : "–"}</a></td>
      <td class="num"><a href="#/runs/${encodeURIComponent(r.run_id)}" class="dim">${esc(ago(r.updated))}</a></td></tr>`).join("");
  const cards = shown.map((r) => `<li><a href="#/runs/${encodeURIComponent(r.run_id)}"><span class="t">${esc(taskTitle(r.task_profile))}</span>${runChip(r)}
      <span class="m">${esc(LEVEL_LABEL[r.reasoning_level] || r.reasoning_level || "–")} · ${num(r.model_calls)} calls · ${r.elapsed_seconds != null ? clock(r.elapsed_seconds) : "–"}${r.updated ? ` · ${esc(ago(r.updated))}` : ""}<br>${esc(r.run_id)}</span></a></li>`).join("");
  return `<div class="page-head"><div><div class="eyebrow">runs</div><h1>Recorded runs</h1><p class="lede">Every run keeps its full event record. Open one to replay it on the recorder.</p></div>
      ${readOnly ? "" : `<button type="button" class="btn primary" data-act="new-run">New run</button>`}</div>
    <div class="toolbar"><input type="search" id="runSearch" placeholder="Search task, id or summary" value="${esc(ui.query || "")}" aria-label="Search runs"><div class="filter" role="group" aria-label="Filter runs">${filters}</div></div>
    ${shown.length ? `<table class="runs-table"><thead><tr><th>result</th><th>task</th><th>reasoning</th><th class="num">calls</th><th class="num">wall</th><th class="num">when</th></tr></thead><tbody>${rows}</tbody></table><ul class="run-cards">${cards}</ul>`
      : `<div class="empty"><h2>${runs.length ? "Nothing matches" : "No runs yet"}</h2><p>${runs.length ? "Clear the search or filter." : readOnly ? "This showcase has no recordings." : "Start one with New run."}</p></div>`}`;
}

/* ---------- one run ---------- */

const TABS = [["recorder", "Recorder"], ["process", "Process"], ["files", "Files"], ["checks", "Checks"], ["log", "Log"]];

export function runView(state, run, ui, ctx) {
  const v = run.verdict;
  const summary = state.summary || {};
  const last = run.evals[run.evals.length - 1];
  const active = run.alarms.filter((a) => a.state !== "RTN").length;
  const fileFlags = [...run.files.values()].flat().filter((e) => e.kind === "X" || e.kind === "P!").length;
  const running = state.status === "running" || state.status === "waiting_approval";
  const actions = ctx.readOnly ? "" : [
    running ? `<button type="button" class="btn" data-act="stop-run">Stop</button>` : "",
    state.status === "interrupted" ? `<button type="button" class="btn primary" data-act="resume-run">Resume</button>` : "",
    `<button type="button" class="btn" data-act="rerun">Run again</button>`,
  ].join("");
  const approval = state.approval?.status === "pending" ? `<div class="approval-banner" role="alert"><span class="pri pri-2">2</span><p><b>Approval needed.</b> The model wants to ${esc(state.approval.action)}${state.approval.summary?.path ? ` <span class="mono">${esc(state.approval.summary.path)}</span>` : ""}${state.approval.summary?.command ? ` <span class="mono">${esc(state.approval.summary.command)}</span>` : ""}.</p>
      ${ctx.readOnly ? "" : `<button type="button" class="btn warn" data-act="approve-run">Approve</button><button type="button" class="btn" data-act="deny-run">Deny</button>`}</div>` : "";
  const tabs = TABS.map(([id, label]) => {
    const count = id === "process" && active ? ` <span class="count">${active}</span>` : id === "files" && fileFlags ? ` <span class="count">${fileFlags}</span>` : "";
    return `<a href="#/runs/${encodeURIComponent(state.run_id)}/${id}" aria-current="${ui.tab === id ? "page" : "false"}">${label}${count}</a>`;
  }).join("");
  const body = { recorder: recorderTab, process: processTab, files: filesTab, checks: checksTab, log: logTab }[ui.tab] || recorderTab;
  return `<section class="verdict tone-${esc(v.tone)}" aria-label="Verdict">
      <div class="verdict-main"><div class="verdict-word">${v.key === "running" ? '<span class="live-dot" aria-hidden="true"></span>' : ""}<strong>${esc(v.word)}</strong>${v.tag ? `<span class="tag">${esc(v.tag)}</span>` : ""}</div>
        <p class="verdict-line">${last ? `${num(last.passedCount)} of ${num(last.total)} checks pass. ` : ""}${esc(v.key === "blocked" || v.key === "error" ? humanReason(v.line) : v.line)}</p>
        <p class="verdict-sub">${esc(state.run_id)} · ${esc(state.workspace_mode || "")} workspace · approvals ${esc(state.approval_mode || "auto")}</p></div>
      <dl class="readouts">
        <div><dt>task</dt><dd title="${esc(taskTitle(state.task_profile))}">${esc(taskTitle(state.task_profile))}</dd></div>
        <div><dt>model</dt><dd title="${esc(state.model || summary.model || "")}">${esc(state.model || summary.model || "–")}</dd></div>
        <div><dt>reasoning</dt><dd>${esc(state.reasoning?.label || LEVEL_LABEL[state.reasoning?.level] || state.reasoning?.level || "–")}</dd></div>
        <div><dt>calls</dt><dd>${num(state.model_calls)} · ${num(state.tool_calls)}</dd></div>
        <div><dt>wall</dt><dd>${clock(summary.elapsed_seconds ?? run.duration)}</dd></div>
        <div><dt>checks</dt><dd class="${last && !last.passed ? "amber" : ""}">${last ? `${num(last.passedCount)} / ${num(last.total)}` : "–"}</dd></div>
      </dl>
      ${actions ? `<div class="actions" style="width:100%">${actions}</div>` : ""}
    </section>${approval}
    <nav class="tabs" aria-label="Run views">${tabs}</nav>
    ${body(state, run, ui, ctx)}`;
}

function humanReason(line) {
  return String(line || "")
    .replace(/^evaluator repair extension exhausted; remaining checks: /, "Repair budget spent. Still failing: ")
    .replace(/^recovery exhausted for (\w+) after (\d+) attempts: /, (_, kind, n) => `Gave up after ${n} attempts (${kind.replace(/_/g, " ")}): `)
    .replace(/^reached the (\d+)-turn limit without a finish action/, "Ran out of turns ($1) before finishing.");
}

function transport(run, ui, state) {
  const D = Math.max(1, run.duration);
  const upto = ui.upto ?? D;
  const live = state.status === "running" && ui.follow;
  return `<div class="transport">
    <span class="title">RECORDER${live ? ' · <span class="cyan">LIVE</span>' : ""}</span>
    <button type="button" class="btn icon small" data-act="play" aria-label="${ui.playing ? "Pause replay" : "Replay this run"}">${ui.playing ? ICON.pause : ICON.play}</button>
    <select id="speed" aria-label="Replay speed">${[1, 4, 16, 64].map((s) => `<option value="${s}" ${Number(ui.speed) === s ? "selected" : ""}>${s}×</option>`).join("")}</select>
    <input type="range" id="scrub" min="0" max="${D.toFixed(1)}" step="0.1" value="${upto.toFixed(1)}" aria-label="Recorder position">
    <span class="pos">${clock(upto)} / ${clock(D)}</span>
  </div>`;
}

function checksCard(run) {
  const last = run.evals[run.evals.length - 1];
  if (!last) return `<section class="panel"><div class="panel-head"><h3>evaluator</h3></div><div class="panel-body"><p class="dim" style="margin:0">Not graded yet. Ungated runs are never graded.</p></div></section>`;
  const failing = Object.entries(last.checks).filter(([, ok]) => !ok).map(([k]) => k);
  const passing = Object.entries(last.checks).filter(([, ok]) => ok).map(([k]) => k);
  const byId = new Map((last.findings || []).map((f) => [f.id, f]));
  const repairFindings = new Map((run.repair?.findings || []).map((f) => [f.id, f]));
  return `<section class="panel"><div class="panel-head"><h3>evaluator · ${num(last.passedCount)} / ${num(last.total)}</h3><span class="mono dim" style="font-size:12px">${run.evals.length} evaluation${run.evals.length === 1 ? "" : "s"}</span></div><div class="panel-body">
    ${failing.length ? `<ul class="findings">${failing.map((id) => {
      const f = byId.get(id) || repairFindings.get(id) || {};
      return `<li class="finding"><div class="id">▲ ${esc(id)}</div>${f.message ? `<p>${esc(f.message)}</p>` : ""}${f.evidence ? `<div class="evidence">observed: ${esc(f.evidence)}</div>` : ""}</li>`;
    }).join("")}</ul>` : `<p class="result-line ok" style="margin:0">✓ every check passed</p>`}
    ${passing.length ? `<p class="passlist">pass: ${passing.map(esc).join(" · ")}</p>` : ""}</div></section>`;
}

function recorderTab(state, run, ui, ctx) {
  const detail = turnDetail(run, state, ui.turn);
  const compactDetail = turnDetail(run, state, ui.turn, { compact: true });
  return `<section class="panel recorder" aria-label="Flight recorder">${transport(run, ui, state)}${horizontalRecorder(run, state, ui)}${verticalTape(run, state, ui, compactDetail)}</section>
    <div class="split">
      <section class="panel grow turn-panel" aria-label="Turn detail"><div class="panel-body">${detail}</div></section>
      <div class="side">${checksCard(run)}
        <section class="panel"><div class="panel-head"><h3>alarms</h3><a href="#/runs/${encodeURIComponent(state.run_id)}/process" class="mono" style="font-size:12px">all ${run.alarms.length}</a></div><div class="panel-body">${alarmList(run.alarms, { limit: 4 })}</div></section>
      </div>
    </div>${modelSummary(state)}`;
}

function processTab(state, run, ui, ctx) {
  const proc = ctx.process;
  return `<section class="panel" aria-label="Process"><div class="panel-head"><h2>process · ${esc(taskTitle(state.task_profile))}</h2><span class="mono dim" style="font-size:12px">filled = evidence recorded · heavy outline = current phase</span></div><div class="panel-body" style="padding-top:0">${processView(proc)}</div></section>
    <div class="split">
      <section class="panel grow" aria-label="Alarm summary"><div class="panel-head"><h2>alarm summary · ${run.alarms.length}</h2><span class="mono dim" style="font-size:12px">LATCHED ended the run · RTN returned to normal</span></div><div class="panel-body">${alarmList(run.alarms)}</div></section>
      <aside class="side"><section class="panel" aria-label="Model faceplate"><div class="panel-head"><h3>model ${esc(state.provider?.provider === "openai_compatible" ? "· api" : "· local")}</h3></div><div class="panel-body" style="display:flex;flex-direction:column;gap:16px">
        <div><div style="font:700 21px var(--sans)">${esc(state.model || "–")}</div><div class="dim mono" style="font-size:12px;margin-top:2px">${esc((state.provider?.endpoint || "").replace(/^https?:\/\//, ""))}${state.reasoning?.budget != null ? ` · ${num(state.reasoning.budget)} reasoning` : ""}</div></div>
        <div class="state-plate">STATE <b>${esc(run.verdict.word)}</b></div>
        ${gaugeList(run, state)}</div></section></aside>
    </div>`;
}

function filesTab(state, run, ui) {
  return `<section class="panel" aria-label="File lens"><div class="panel-head"><h2>files · what the model did to each, turn by turn</h2></div><div class="panel-body">${fileLens(run, ui)}</div></section>
    <section class="panel" style="margin-top:20px" aria-label="File event"><div class="panel-body">${ui.file ? fileEventDetail(run, ui.file, ui.turn) : fileEventDetail(run, "", 0)}</div></section>
    ${ui.preview ? `<section class="panel" style="margin-top:20px" aria-label="Current file"><div class="panel-head"><h3>${esc(ui.preview.path)} · current file</h3><button type="button" class="btn small" data-act="close-preview">Close</button></div><div class="panel-body" style="padding-top:0">${ui.preview.error ? `<p class="amber">${esc(ui.preview.error)}</p>` : `<pre class="code">${esc(ui.preview.content ?? "")}</pre>`}</div></section>` : ""}
    <section class="panel" style="margin-top:20px"><div class="panel-head"><h3>project files now</h3></div><div class="panel-body">${(state.files || []).length ? `<div class="actions">${state.files.map((f) => `<button type="button" class="btn small mono" data-act="open-file" data-file="${esc(f.path)}">${esc(f.path)} <span class="dim">${num(f.bytes ?? f.size)} B</span></button>`).join("")}</div>` : '<p class="dim" style="margin:0">No files.</p>'}</div></section>`;
}

function checksTab(state, run) {
  const summary = state.summary || {};
  const evidence = summary.workflow_evidence || state.progress?.workflow_evidence || {};
  const review = state.review || {};
  const evals = run.evals.map((e, i) => {
    const failing = Object.entries(e.checks).filter(([, ok]) => !ok).map(([k]) => k);
    return `<li><span class="pri ${e.passed ? "" : "pri-2"}" style="${e.passed ? "background:var(--model);color:#071214" : ""}">${e.passed ? "✓" : "2"}</span><span class="t">${clock(e.at)}</span><span><span class="tag">evaluation ${i + 1} · ${num(e.passedCount)}/${num(e.total)}</span><span class="txt">${failing.length ? `failing: ${failing.map(esc).join(", ")}` : "all checks passed"}</span></span><span class="st">T${esc(e.turn ?? "")}</span></li>`;
  }).join("");
  const skills = state.skills?.resolved?.map((s) => s.name) || state.skills?.defaults || [];
  return `<div class="split" style="margin-top:0">
      <div class="grow" style="display:flex;flex-direction:column;gap:20px">
        ${checksCard(run)}
        <section class="panel"><div class="panel-head"><h3>evaluations</h3></div><div class="panel-body">${evals ? `<ul class="alarm-list">${evals}</ul>` : '<p class="dim" style="margin:0">None.</p>'}</div></section>
        ${modelSummary(state, true)}
        <section class="panel"><div class="panel-head"><h3>task</h3></div><div class="panel-body" style="padding-top:0"><pre class="code wrap">${esc(run.task || summary.task || "")}</pre></div></section>
      </div>
      <aside class="side">
        <section class="panel"><div class="panel-head"><h3>finish gates</h3></div><div class="panel-body"><ul class="alarm-list">${["inspect", "plan", "implement", "verify", "review"].map((g) => `<li style="grid-template-columns:24px minmax(0,1fr)"><span class="pri" style="${evidence[g] ? "background:var(--model);color:#071214" : "border:2px solid var(--line-2)"}">${evidence[g] ? "✓" : ""}</span><span><span class="tag">${g.toUpperCase()}</span><span class="txt">${evidence[g] ? "evidence recorded" : "no evidence at the end"}</span></span></li>`).join("")}</ul></div></section>
        <section class="panel"><div class="panel-head"><h3>review packet</h3></div><div class="panel-body"><p style="margin:0" class="${review.status === "stale" ? "amber" : ""}">${esc(review.status || "none")}${review.status === "stale" ? " · files changed after the last diff review" : ""}</p>
          ${(review.changed_files || []).length ? `<p class="passlist">${review.changed_files.map((f) => `${esc(f.status)} ${esc(f.path)} (${num(f.after_bytes)} B)`).join("<br>")}</p>` : ""}</div></section>
        <section class="panel"><div class="panel-head"><h3>settings</h3></div><div class="panel-body"><dl class="kv" style="margin:0">
          <div><dt>provider</dt><dd>${esc(state.provider?.label || state.provider?.provider || "–")}</dd></div><div><dt>max turns</dt><dd>${num(state.max_turns)}</dd></div>
          <div><dt>window</dt><dd>${num(state.model_context_tokens)}</dd></div><div><dt>reply cap</dt><dd>${num(state.reasoning?.max_tokens)}</dd></div>
          <div style="grid-column:1/-1"><dt>skills</dt><dd style="white-space:normal">${skills.map(esc).join(", ") || "–"}</dd></div></dl></div></section>
      </aside></div>`;
}

function modelSummary(state, always = false) {
  const text = state.summary?.summary || state.summary?.finish_summary || "";
  const finish = state.summary?.finish?.summary || "";
  const body = finish || (state.status === "success" ? text : "");
  if (!body && !always) return "";
  return `<section class="panel" style="margin-top:20px"><div class="panel-head"><h3>The model's own summary <small>unverified</small></h3></div><div class="panel-body"><p style="margin:0;white-space:pre-wrap">${esc(body || "The model did not finish with a summary.")}</p></div></section>`;
}

function logTab(state, run, ui, ctx) {
  const types = [...new Set(ctx.events.map((e) => e.event))].sort();
  const pick = ui.logType || "";
  const list = ctx.events.filter((e) => !pick || e.event === pick);
  const shown = list.slice(-400);
  const t0 = run.t0;
  return `<div class="toolbar"><select id="logType" aria-label="Event type" style="height:44px;background:var(--well);border:1px solid var(--line-2);border-radius:4px;padding:0 10px"><option value="">all events (${ctx.events.length})</option>${types.map((t) => `<option value="${esc(t)}" ${pick === t ? "selected" : ""}>${esc(t)} (${ctx.events.filter((e) => e.event === t).length})</option>`).join("")}</select></div>
    <section class="panel"><div class="panel-body" style="padding-top:6px">${shown.length ? `<ul class="alarm-list">${shown.map((e) => {
      const data = { ...(e.data || {}) };
      delete data.reasoning_content;
      const at = t0 ? (Date.parse(e.timestamp) - t0) / 1000 : 0;
      return `<li style="grid-template-columns:56px minmax(0,1fr)"><span class="t">${clock(at)}</span><details><summary class="tag" style="cursor:pointer">${esc(e.event)}${data.turn != null ? ` · T${esc(data.turn)}` : ""}</summary><pre class="code">${esc(JSON.stringify(data, null, 2).slice(0, 12000))}</pre></details></li>`;
    }).join("")}</ul>` : '<p class="dim">No events.</p>'}${list.length > shown.length ? `<p class="dim mono" style="font-size:12px">showing the last ${shown.length} of ${list.length}</p>` : ""}</div></section>
    ${(state.output || []).length ? `<section class="panel" style="margin-top:20px"><div class="panel-head"><h3>process output</h3></div><div class="panel-body" style="padding-top:0"><pre class="code">${esc(state.output.slice(-200).join("\n"))}</pre></div></section>` : ""}`;
}

/* ---------- chats ---------- */

export function chatView(sessions, session, ui, ctx) {
  const list = `<ul class="chat-list" aria-label="Chats">${sessions.length ? sessions.map((s) => `<li><a href="#/chats/${encodeURIComponent(s.session_id)}" aria-current="${session && s.session_id === session.session_id ? "page" : "false"}">${esc(chatTitle(s.conversation))}<small>${esc(s.session_id)} · ${num((s.conversation || []).length)} messages</small></a></li>`).join("") : '<li class="dim" style="padding:12px 14px">No chats yet.</li>'}</ul>`;
  if (!session) {
    return `<div class="chat-layout">${list}<div class="chat-main"><div class="empty"><h2>${sessions.length ? "Pick a chat" : "No chats yet"}</h2><p>Chats are ongoing conversations with the model in a project folder. Runs are the graded trials.</p>${ctx.readOnly ? "" : `<button type="button" class="btn primary" data-act="new-chat">New chat</button>`}</div></div></div>`;
  }
  const { groups, live } = chatGroups(session.events);
  const convo = session.conversation || [];
  const assistantCount = convo.filter((m) => m.role === "assistant").length;
  const offset = groups.length - assistantCount;
  let ai = 0;
  const work = (g) => {
    if (!g || (!g.tools.length && !g.marks.length)) return "";
    const failed = g.tools.filter((t) => t.failed).length;
    return `<div class="work"><details><summary><span class="tglyphs" style="display:inline-flex">${g.tools.map((t) => `<span class="chip ${t.failed ? "bad" : ""}" aria-hidden="true">${esc(t.failed ? "▲" : t.glyph)}</span>`).join("")}</span> ${num(g.calls)} calls · ${num(g.tools.length)} tools${failed ? ` · <span class="amber">${failed} failed</span>` : ""}${g.marks.length ? ` · <span class="amber">${esc(g.marks.join(", "))}</span>` : ""}${g.seconds ? ` · ${clock(g.seconds)}` : ""}</summary>
      <ul>${g.tools.map((t) => `<li>${esc(t.action)} ${esc(t.path)}${t.failed ? ` <span class="amber">▲ ${esc(t.error.slice(0, 160))}</span>` : ""}</li>`).join("")}</ul></details></div>`;
  };
  const msgs = convo.map((m) => {
    if (m.role === "assistant") {
      const g = groups[offset + ai];
      ai += 1;
      return `<div class="msg assistant">${work(g)}${esc(m.content)}</div>`;
    }
    return `<div class="msg user">${esc(m.content)}</div>`;
  }).join("");
  const job = session.job || {};
  const busy = session.busy || job.status === "running";
  let banner = "";
  if (job.status === "waiting_approval" || session.approval?.status === "pending") {
    banner = `<div class="job-banner warn" role="alert"><span class="pri pri-2">2</span><p><b>Approval needed.</b> ${esc(session.approval?.action || "a project change")} ${esc(session.approval?.summary?.path || session.approval?.summary?.command || "")}</p>${ctx.readOnly ? "" : `<button type="button" class="btn warn small" data-act="approve-job">Approve</button><button type="button" class="btn small" data-act="deny-job">Deny</button>`}</div>`;
  } else if (job.status === "interrupted" || job.status === "failed") {
    banner = `<div class="job-banner warn" role="alert"><p><b>${job.status === "interrupted" ? "This turn was interrupted." : "This turn failed."}</b> ${esc(job.error || session.last_error || "")}</p>${ctx.readOnly ? "" : `<button type="button" class="btn small" data-act="retry-job">Retry</button>`}</div>`;
  } else if (busy) {
    banner = `<div class="job-banner"><span class="live-dot" aria-hidden="true"></span><p>Working · step ${num(job.current_step)} · ${esc(String(job.last_action || "thinking").replace(/_/g, " "))}${live.tools.length ? ` · <span class="tglyphs" style="display:inline-flex;vertical-align:middle">${live.tools.map((t) => `<span class="chip ${t.failed ? "bad" : ""}">${esc(t.failed ? "▲" : t.glyph)}</span>`).join("")}</span>` : ""}</p>${ctx.readOnly ? "" : `<button type="button" class="btn small" id="stopJobButton" data-act="stop-job">Stop</button>`}</div>`;
  }
  const levels = ctx.levels.length ? ctx.levels : [{ value: session.reasoning?.level || "standard", label: session.reasoning?.label || "Standard" }];
  return `<div class="chat-layout">${list}<div class="chat-main">
    <div class="chat-bar"><a href="#/chats" class="btn icon small" aria-label="All chats">${ICON.left}</a><h1>${esc(chatTitle(convo))}</h1><div class="bar-tools">
      <select id="reasoningSelect" aria-label="Reasoning" ${ctx.readOnly ? "disabled" : ""}>${levels.map((l) => `<option value="${esc(l.value)}" ${l.value === session.reasoning?.level ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select>
      <select id="approvalSelect" aria-label="Approvals" ${ctx.readOnly ? "disabled" : ""}><option value="auto" ${session.approval_mode !== "confirm" ? "selected" : ""}>auto-apply</option><option value="confirm" ${session.approval_mode === "confirm" ? "selected" : ""}>ask before changes</option></select>
      <button type="button" class="btn small" data-act="chat-files">Files ${num((session.files || []).length)}</button></div></div>
    ${ui.chatFiles ? `<section class="panel" style="margin-top:12px"><div class="panel-body">${(session.files || []).length ? `<div class="actions">${session.files.map((f) => `<button type="button" class="btn small mono" data-act="open-chat-file" data-file="${esc(f.path)}">${esc(f.path)}</button>`).join("")}</div>` : '<p class="dim" style="margin:0">No files in this project.</p>'}${ui.preview ? (ui.preview.error ? `<p class="amber">${esc(ui.preview.error)}</p>` : `<pre class="code">${esc(ui.preview.content ?? "")}</pre>`) : ""}</div></section>` : ""}
    <div class="messages" id="chatMessages">${msgs || '<p class="dim">Say what you want done in this project.</p>'}</div>
    ${banner}
    <form class="composer" data-form="send"><textarea id="chatInput" rows="1" placeholder="${ctx.readOnly ? "Read-only showcase" : "Message the model"}" aria-label="Message" ${ctx.readOnly || busy ? "disabled" : ""}>${esc(ui.draft || "")}</textarea><button type="submit" class="btn primary" id="sendButton" ${ctx.readOnly || busy ? "disabled" : ""}>Send</button></form>
  </div></div>`;
}
