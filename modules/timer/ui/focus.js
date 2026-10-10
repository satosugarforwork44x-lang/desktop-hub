// timer/ui/focus.js — フォーカスモードの「音の輪」。
//   ・絹のように細く光る線（音の波形）を何本も重ねて輪にし、それぞれが少しずつずれて波打つ
//   ・輪の外側には、スペクトラムのような細い線が放射状に立ち、鼓動のたびに伸びる
//   ・鼓動（ドクン・ドクン）で輪全体がふくらみ、粒子が外へはじける
//   ・色は円周に沿ってテーマのグラデーション 3 色が回る。残り時間の分だけ明るく、過ぎた分は暗い
// createFocusRing(canvas) → { start, stop, update(残りの割合, 状態), retheme }

const STRANDS = 16;        // 光る線の本数
const SPIKES = 200;        // 外側の放射線の本数
const SPARKS = 140;        // はじける粒子の数
const BPM = 56;            // 鼓動の速さ（落ち着いた安静時くらい）
const STEP = Math.PI / 120;

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  return ["--c1-rgb", "--c2-rgb", "--c3-rgb"].map((k) => cs.getPropertyValue(k).split(",").map(Number));
}
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

// 鼓動の形: 1 拍の中で「強い山 → 少しあとに弱い山」（0〜約1）
function beat(phase) {
  const bump = (x, at, w) => Math.exp(-((x - at) ** 2) / w);
  return bump(phase, 0.06, 0.0018) + 0.55 * bump(phase, 0.24, 0.0026);
}

// なめらかな揺らぎ（いくつかの sin を重ねた疑似ノイズ）
const wob = (a, t, k) =>
  Math.sin(a * 3 + t * 0.9 + k * 0.7) * 0.5 + Math.sin(a * 5 - t * 1.3 + k * 1.9) * 0.3 + Math.sin(a * 9 + t * 2.1 - k) * 0.2;

export function createFocusRing(canvas) {
  const ctx = canvas.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let colors = themeColors();
  let progress = 1;          // 残りの割合（1 = 全部残っている）
  let state = "running";     // running / paused / done / idle
  let raf = 0;
  let t0 = performance.now();
  let lastBeat = 0;
  const sparks = [];
  const spikeSeed = Array.from({ length: SPIKES }, () => [Math.random() * 10, 0.6 + Math.random() * 0.8]);

  const colorAt = (u) => {   // 円周上の位置 u（0〜1）の色。c1 → c2 → c3 → c1 と一周する
    const [c1, c2, c3] = colors;
    u = ((u % 1) + 1) % 1;
    return u < 1 / 3 ? mix(c1, c2, u * 3) : u < 2 / 3 ? mix(c2, c3, (u - 1 / 3) * 3) : mix(c3, c1, (u - 2 / 3) * 3);
  };

  function resize() {
    const dpr = devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function conic(cx, cy, rot, alpha, dimAlpha) {
    // 円周に沿ったグラデーション。12 時から時計回りに「残り」の範囲を明るく
    const g = ctx.createConicGradient(-Math.PI / 2, cx, cy);
    const n = 24;
    for (let i = 0; i <= n; i++) {
      const u = i / n;
      const c = colorAt(u + rot);
      const lit = state === "idle" || state === "done" || u <= progress;
      g.addColorStop(u, `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${lit ? alpha : dimAlpha})`);
    }
    return g;
  }

  function spawn(cx, cy, R, n, strength) {
    for (let i = 0; i < n && sparks.length < SPARKS; i++) {
      const a = Math.random() * Math.PI * 2;
      const sp = (0.25 + Math.random() * 0.9) * strength;
      sparks.push({ a, r: R * (1.02 + Math.random() * 0.08), v: sp, life: 1, size: 0.6 + Math.random() * 1.6, c: colorAt(a / (Math.PI * 2) + 0.25) });
    }
  }

  function frame(now) {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const t = reduce ? 0 : (now - t0) / 1000;
    const light = document.documentElement.dataset.mode === "light";
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * 0.3;
    const alive = state === "running" && !reduce;
    const ph = ((t * BPM) / 60) % 1;
    const pulse = alive ? beat(ph) : 0;
    const calm = state === "paused" ? 0.3 : state === "idle" ? 0.55 : 1;
    const rot = t * 0.02;
    ctx.globalCompositeOperation = light ? "source-over" : "lighter";

    // 中心のほのかな光
    const [, c2] = colors;
    const glow = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.5);
    glow.addColorStop(0, `rgba(${c2[0]}, ${c2[1]}, ${c2[2]}, ${(light ? 0.06 : 0.1) + pulse * 0.06})`);
    glow.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, h);

    // ① 光る線（絹の波形）。1 本ずつ少しずれた揺れ方で輪を描く
    const amp = R * (0.05 + pulse * 0.07) * calm;
    ctx.lineWidth = light ? 1 : 0.9;
    ctx.shadowBlur = light ? 0 : 10;
    for (let k = 0; k < STRANDS; k++) {
      const kk = k / (STRANDS - 1);
      const off = (kk - 0.5) * R * 0.12;                 // 線どうしの間隔（中央が詰まり、外側が広がる）
      ctx.strokeStyle = conic(cx, cy, rot + kk * 0.06, light ? 0.35 : 0.3 + 0.25 * (1 - Math.abs(kk - 0.5) * 2), light ? 0.08 : 0.06);
      const sc = colorAt(kk + rot);
      ctx.shadowColor = `rgba(${sc[0]}, ${sc[1]}, ${sc[2]}, .8)`;
      ctx.beginPath();
      for (let a = 0; a <= Math.PI * 2 + STEP / 2; a += STEP) {
        // 波の大きさは円周で変える（音声の波形のように、静かな所と大きく揺れる所を作る）
        const env = 0.35 + 0.65 * Math.max(0, Math.sin(a * 2 + t * 0.35)) ** 2 + 0.25 * Math.sin(a * 3 - t * 0.2);
        const r = R + off * (1 + pulse * 0.8) + amp * env * wob(a, t, k * 0.35) * (1 + kk * 0.6);
        const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
        a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // ② 外側の放射線（スペクトラム）。鼓動で伸び、円周の場所ごとに長さが揺らぐ
    ctx.strokeStyle = conic(cx, cy, rot, light ? 0.55 : 0.6, light ? 0.12 : 0.1);
    ctx.lineWidth = Math.max(1, R * 0.012);
    ctx.lineCap = "round";
    ctx.beginPath();
    for (let i = 0; i < SPIKES; i++) {
      const a = (i / SPIKES) * Math.PI * 2;
      const [seed, sp] = spikeSeed[i];
      const n = 0.5 + 0.5 * Math.sin(seed + t * 2.3 * sp) * Math.sin(seed * 1.7 - t * 1.1);
      const big = Math.max(0, Math.sin(a * 2 + t * 0.35)) ** 2;     // 光る線と同じ場所が大きく動く
      const len = R * (0.015 + (0.05 + 0.16 * big) * n * calm + pulse * 0.1 * (0.4 + n));
      const r0 = R * 1.12 + pulse * R * 0.04;
      ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
      ctx.lineTo(cx + Math.cos(a) * (r0 + len), cy + Math.sin(a) * (r0 + len));
    }
    ctx.stroke();

    // ③ 鼓動のたびに、粒子が外へはじける
    if (alive && ph < 0.08 && now - lastBeat > 400) {
      lastBeat = now;
      spawn(cx, cy, R * 1.14, 26, R * 0.012);
    }
    for (let i = sparks.length - 1; i >= 0; i--) {
      const p = sparks[i];
      p.r += p.v * (reduce ? 0 : 1);
      p.v *= 0.985;
      p.life -= 0.012;
      if (p.life <= 0) { sparks.splice(i, 1); continue; }
      ctx.fillStyle = `rgba(${p.c[0]}, ${p.c[1]}, ${p.c[2]}, ${p.life * (light ? 0.6 : 0.85)})`;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(p.a) * p.r, cy + Math.sin(p.a) * p.r, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
    if (!reduce) raf = requestAnimationFrame(frame);
  }

  const ro = new ResizeObserver(() => { resize(); if (reduce) frame(performance.now()); });
  ro.observe(canvas);
  resize();

  return {
    start() { cancelAnimationFrame(raf); t0 = performance.now(); raf = requestAnimationFrame(frame); },
    stop() { cancelAnimationFrame(raf); },
    update(remainRatio, st) {
      progress = Math.max(0, Math.min(1, remainRatio));
      state = st;
      if (reduce) frame(performance.now());
    },
    retheme() { colors = themeColors(); },
  };
}
