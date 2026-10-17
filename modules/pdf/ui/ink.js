// pdf/ui/ink.js — 手書きの板。マウス・ペン・指で描いて、SVG（線だけ・背景なし）にして返す。
//   ・色は 3 色（墨・青・赤）、太さは 2 つ、1 本ずつ取り消し、全部消す
//   ・ダークの画面では、墨が白く見えるように反転して見せる（保存する SVG は墨のまま。ライトでもそのまま読める）
//   ・ペンの筆圧に対応（対応していないマウスは一定の太さ）
const COLORS = [["ink", "#1f2430"], ["blue", "#2f6fe0"], ["red", "#e0483e"]];
const WIDTHS = [["thin", 2.2], ["thick", 5]];

export function inkPad(host, t) {
  return new Promise((done) => {
    const wrap = document.createElement("div");
    wrap.className = "ink-wrap";
    wrap.innerHTML = `
      <div class="ink-pad" role="dialog" aria-label="${t("md.ink")}">
        <div class="ink-bar">
          <span class="ink-colors"></span><span class="pv-sep"></span><span class="ink-widths"></span>
          <span class="pv-grow"></span>
          <button class="btn" data-a="undo"></button>
          <button class="btn" data-a="clear"></button>
        </div>
        <div class="ink-board"><canvas class="ink-canvas"></canvas></div>
        <div class="ink-foot">
          <button class="btn" data-a="cancel"></button>
          <button class="btn primary" data-a="ok"></button>
        </div>
      </div>`;
    host.append(wrap);
    const cv = wrap.querySelector("canvas");
    const g = cv.getContext("2d");
    const strokes = [];               // [{c, w, pts: [[x, y, pressure], …]}]
    let color = COLORS[0][1], width = WIDTHS[0][1], cur = null;
    const label = { undo: t("md.inkUndo"), clear: t("md.inkClear"), cancel: t("md.inkCancel"), ok: t("md.inkInsert") };
    for (const [a, s] of Object.entries(label)) wrap.querySelector(`[data-a="${a}"]`).textContent = s;

    const pick = (box, list, onPick, cls) => {
      for (const [name, v] of list) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = `ink-${cls}`;
        b.title = t(`md.ink.${name}`);
        b.setAttribute("aria-label", b.title);
        if (cls === "color") b.style.setProperty("--c", v);
        else b.style.setProperty("--w", `${v * 1.6}px`);
        b.addEventListener("click", () => { onPick(v); box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); });
        box.append(b);
      }
      box.querySelector("button").setAttribute("aria-pressed", "true");
    };
    pick(wrap.querySelector(".ink-colors"), COLORS, (v) => { color = v; }, "color");
    pick(wrap.querySelector(".ink-widths"), WIDTHS, (v) => { width = v; }, "width");

    // 板の大きさ: 窓の幅に合わせ、横長（3:2）。描いた点は CSS の px で持つ
    let W = 0, H = 0;
    function size() {
      const r = cv.getBoundingClientRect();
      W = r.width; H = r.height;
      const dpr = devicePixelRatio || 1;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      redraw();
    }
    const lw = (s, p) => s.w * (0.55 + 0.9 * (p ?? 0.5));
    function drawStroke(s) {
      g.strokeStyle = s.c; g.fillStyle = s.c; g.lineCap = "round"; g.lineJoin = "round";
      const p = s.pts;
      if (p.length === 1) { g.beginPath(); g.arc(p[0][0], p[0][1], lw(s, p[0][2]) / 2, 0, Math.PI * 2); g.fill(); return; }
      for (let i = 1; i < p.length; i++) {
        g.lineWidth = lw(s, p[i][2]);
        g.beginPath(); g.moveTo(p[i - 1][0], p[i - 1][1]); g.lineTo(p[i][0], p[i][1]); g.stroke();
      }
    }
    function redraw() { g.clearRect(0, 0, W, H); strokes.forEach(drawStroke); }

    cv.addEventListener("pointerdown", (e) => {
      cv.setPointerCapture(e.pointerId);
      const r = cv.getBoundingClientRect();
      cur = { c: color, w: width, pts: [[e.clientX - r.left, e.clientY - r.top, e.pointerType === "pen" ? e.pressure : 0.5]] };
      strokes.push(cur);
      drawStroke(cur);
    });
    cv.addEventListener("pointermove", (e) => {
      if (!cur) return;
      const r = cv.getBoundingClientRect();
      for (const ev of e.getCoalescedEvents?.() || [e]) {
        cur.pts.push([ev.clientX - r.left, ev.clientY - r.top, ev.pointerType === "pen" ? ev.pressure : 0.5]);
      }
      const p = cur.pts, n = p.length;
      g.strokeStyle = cur.c; g.lineCap = "round"; g.lineWidth = lw(cur, p[n - 1][2]);
      g.beginPath(); g.moveTo(p[Math.max(0, n - 2)][0], p[Math.max(0, n - 2)][1]); g.lineTo(p[n - 1][0], p[n - 1][1]); g.stroke();
    });
    const end = () => { cur = null; };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);

    // SVG にする: 描いた範囲だけを切り出す（余白 8px）。線は太さごとに区切った折れ線
    function toSvg() {
      const all = strokes.flatMap((s) => s.pts);
      if (!all.length) return null;
      const pad = 8;
      const x0 = Math.max(0, Math.min(...all.map((p) => p[0])) - pad), y0 = Math.max(0, Math.min(...all.map((p) => p[1])) - pad);
      const x1 = Math.min(W, Math.max(...all.map((p) => p[0])) + pad), y1 = Math.min(H, Math.max(...all.map((p) => p[1])) + pad);
      const f = (v) => Math.round(v * 10) / 10;
      const parts = strokes.map((s) => {
        const p = s.pts;
        if (p.length === 1) return `<circle cx="${f(p[0][0] - x0)}" cy="${f(p[0][1] - y0)}" r="${f(lw(s, p[0][2]) / 2)}" fill="${s.c}"/>`;
        const d = p.map((q, i) => `${i ? "L" : "M"}${f(q[0] - x0)} ${f(q[1] - y0)}`).join("");
        const avg = p.reduce((a, q) => a + lw(s, q[2]), 0) / p.length;
        return `<path d="${d}" fill="none" stroke="${s.c}" stroke-width="${f(avg)}" stroke-linecap="round" stroke-linejoin="round"/>`;
      });
      const w = f(x1 - x0), h = f(y1 - y0);
      return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${parts.join("")}</svg>`;
    }

    function close(result) {
      removeEventListener("resize", size);
      removeEventListener("keydown", onKey, true);
      wrap.remove();
      done(result);
    }
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(null); }
      if (e.ctrlKey && e.key.toLowerCase() === "z") { e.preventDefault(); strokes.pop(); redraw(); }
    };
    wrap.querySelector('[data-a="undo"]').addEventListener("click", () => { strokes.pop(); redraw(); });
    wrap.querySelector('[data-a="clear"]').addEventListener("click", () => { strokes.length = 0; redraw(); });
    wrap.querySelector('[data-a="cancel"]').addEventListener("click", () => close(null));
    wrap.querySelector('[data-a="ok"]').addEventListener("click", () => close(toSvg()));
    addEventListener("resize", size);
    addEventListener("keydown", onKey, true);
    requestAnimationFrame(size);
  });
}
