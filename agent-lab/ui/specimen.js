// The specimen: a small animated cell that shows what the agent is doing.
// It breathes when idle, churns while the model thinks, flinches on tool calls,
// turns ochre while waiting, glows on a pass and withers on a failure.

const SVG = "http://www.w3.org/2000/svg";
const MODES = {
  idle: { amp: 3.2, speed: 0.5, radius: 50, orbit: 0.25, color: "var(--live)" },
  think: { amp: 7.5, speed: 1.6, radius: 52, orbit: 1.1, color: "var(--live)" },
  tool: { amp: 5.5, speed: 1.1, radius: 54, orbit: 0.7, color: "var(--live)" },
  wait: { amp: 2.5, speed: 0.35, radius: 50, orbit: 0.15, color: "var(--ochre)" },
  pass: { amp: 2.2, speed: 0.45, radius: 55, orbit: 0.3, color: "var(--live)" },
  fail: { amp: 1.4, speed: 0.25, radius: 43, orbit: 0.08, color: "var(--rust)" },
  sleep: { amp: 1.2, speed: 0.18, radius: 46, orbit: 0.05, color: "var(--sage)" },
};

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function blobPath(radius, amp, phase, points = 72) {
  const pts = [];
  for (let i = 0; i < points; i += 1) {
    const th = (i / points) * Math.PI * 2;
    const r = radius + amp * (Math.sin(2 * th + phase * 1.3) * 0.9 + Math.sin(3 * th - phase * 0.9) * 0.6 + Math.sin(5 * th + phase * 2.1) * 0.35);
    pts.push([Math.cos(th) * r, Math.sin(th) * r]);
  }
  let d = "";
  for (let i = 0; i < points; i += 1) {
    const p0 = pts[(i - 1 + points) % points];
    const p1 = pts[i];
    const p2 = pts[(i + 1) % points];
    const p3 = pts[(i + 2) % points];
    if (i === 0) d += `M${p1[0].toFixed(2)},${p1[1].toFixed(2)}`;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return `${d}Z`;
}

let gradientCounter = 0;

export class Specimen {
  constructor(host, { motes = 7 } = {}) {
    this.host = host;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.mode = "idle";
    this.cur = { ...MODES.idle };
    this.t = Math.random() * 10;
    this.jolt = 0;
    this.last = performance.now();
    this.running = false;
    const id = `cell${(gradientCounter += 1)}`;
    const svg = el("svg", { viewBox: "-100 -100 200 200", class: "specimen-svg", "aria-hidden": "true" });
    const defs = el("defs");
    const gradient = el("radialGradient", { id, cx: "40%", cy: "35%", r: "75%" });
    for (const [offset, opacity] of [["0", ".28"], [".55", ".07"], ["1", "0"]]) {
      gradient.appendChild(el("stop", { offset, "stop-opacity": opacity, class: "sp-stop" }));
    }
    const blur = el("filter", { id: `${id}b`, x: "-50%", y: "-50%", width: "200%", height: "200%" });
    blur.appendChild(el("feGaussianBlur", { stdDeviation: "9" }));
    defs.append(gradient, blur);
    this.halo = el("circle", { r: "58", class: "sp-fill", filter: `url(#${id}b)`, opacity: ".12" });
    this.ripples = el("g");
    this.membrane = el("path", { fill: `url(#${id})`, class: "sp-stroke", "stroke-width": "2.2", "stroke-linejoin": "round" });
    this.membrane2 = el("path", { fill: "none", class: "sp-stroke", "stroke-width": "1", opacity: ".35" });
    this.nucleus = el("circle", { r: "14", class: "sp-fill" });
    this.nucleolus = el("circle", { r: "5", class: "sp-hole", opacity: ".55" });
    this.moteGroup = el("g");
    this.motes = Array.from({ length: motes }, (_, i) => {
      const node = el("circle", { class: "sp-fill" });
      this.moteGroup.appendChild(node);
      return { node, a: (i / motes) * Math.PI * 2, r: 70 + (i % 3) * 9, s: 0.6 + (i % 4) * 0.25, size: 1.6 + (i % 3) * 0.9 };
    });
    svg.append(defs, this.halo, this.ripples, this.membrane, this.membrane2, this.nucleus, this.nucleolus, this.moteGroup);
    host.replaceChildren(svg);
    this.svg = svg;
    this.frame = this.frame.bind(this);
    this.onVisibility = () => (document.hidden ? this.stop() : this.start());
    document.addEventListener("visibilitychange", this.onVisibility);
    this.setMode("idle");
    this.draw(0);
    this.start();
  }

  start() {
    if (this.running || this.reduced) return;
    this.running = true;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.frame);
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  destroy() {
    this.stop();
    document.removeEventListener("visibilitychange", this.onVisibility);
  }

  setMode(mode) {
    if (!MODES[mode]) return;
    if (mode === this.mode && this.host.dataset.mode === mode) return;
    this.mode = mode;
    this.host.dataset.mode = mode;
    this.host.style.setProperty("--spec", MODES[mode].color);
    if (this.reduced) {
      Object.assign(this.cur, MODES[mode]);
      this.draw(0);
    }
  }

  pulse(strong = false) {
    this.jolt = strong ? 1 : 0.6;
    if (this.reduced || !this.running) return;
    const ring = el("circle", { r: "50", class: "sp-ring" });
    this.ripples.appendChild(ring);
    const start = performance.now();
    const grow = (now) => {
      const p = Math.min(1, (now - start) / 900);
      ring.setAttribute("r", String(50 + p * 46));
      ring.setAttribute("opacity", (0.7 * (1 - p)).toFixed(3));
      if (p < 1) requestAnimationFrame(grow);
      else ring.remove();
    };
    requestAnimationFrame(grow);
  }

  frame(now) {
    if (!this.running) return;
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    this.draw(dt);
    this.raf = requestAnimationFrame(this.frame);
  }

  draw(dt) {
    const target = MODES[this.mode];
    for (const key of ["amp", "speed", "radius", "orbit"]) this.cur[key] += (target[key] - this.cur[key]) * Math.min(1, dt * 3);
    this.jolt *= Math.pow(0.02, dt);
    this.t += dt * this.cur.speed;
    const t = this.t;
    const radius = this.cur.radius + Math.sin(t * 1.7) * 1.6 + this.jolt * 8;
    this.membrane.setAttribute("d", blobPath(radius, this.cur.amp + this.jolt * 6, t * 2));
    this.membrane2.setAttribute("d", blobPath(radius - 9, this.cur.amp * 0.6, -t * 1.6 + 1));
    const nx = Math.sin(t * 1.1) * 4;
    const ny = Math.cos(t * 0.8) * 3;
    this.nucleus.setAttribute("cx", nx.toFixed(2));
    this.nucleus.setAttribute("cy", ny.toFixed(2));
    this.nucleus.setAttribute("r", (14 + Math.sin(t * 2.4) * 1.2 + this.jolt * 3).toFixed(2));
    this.nucleolus.setAttribute("cx", (nx - 3).toFixed(2));
    this.nucleolus.setAttribute("cy", (ny - 3).toFixed(2));
    this.halo.setAttribute("opacity", (0.1 + this.cur.amp * 0.012 + this.jolt * 0.2).toFixed(3));
    const failing = this.mode === "fail";
    for (const mote of this.motes) {
      mote.a += dt * this.cur.orbit * mote.s;
      const r = mote.r + Math.sin(t * 2 + mote.a * 3) * 4 - (failing ? 18 : 0);
      mote.node.setAttribute("cx", (Math.cos(mote.a) * r).toFixed(2));
      mote.node.setAttribute("cy", (Math.sin(mote.a) * r * 0.92).toFixed(2));
      mote.node.setAttribute("r", String(mote.size));
      mote.node.setAttribute("opacity", failing ? "0.25" : "0.75");
    }
  }
}
