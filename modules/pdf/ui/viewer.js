// pdf/ui/viewer.js — 軽い PDF ビューア（PDF.js）。1 つの PDF = 1 つの窓。
//   連続スクロール・見えているページだけ描く・文字の選択と検索・サムネイル・拡大/幅合わせ・回転・印刷・暗いページ
//   ・画像にする（cli.py）・テキストにする（文字が無いページは OCR）
import * as pdfjsLib from "./vendor/pdfjs/pdf.min.mjs";
import { api, selectBox, TOKEN } from "/ui/js/hub.js";
import { icons } from "/ui/js/icons.js";

const VENDOR = new URL("./vendor/pdfjs/", import.meta.url).href;
pdfjsLib.GlobalWorkerOptions.workerSrc = `${VENDOR}pdf.worker.min.mjs`;

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
const GAP = 14;

export async function mount(el, ctx) {
  const t = ctx.t;
  const key = ctx.instance;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./pdf.css", import.meta.url).href;
  document.head.append(css);

  let info;
  try { info = await ctx.call("doc_info", { key }); }
  catch (e) { el.innerHTML = `<div class="empty"></div>`; el.firstChild.textContent = e.message; return; }
  ctx.setTitle(info.name);

  // ---------- 骨組み ----------
  el.innerHTML = `
    <div class="pv">
      <div class="pv-bar">
        <button class="icon-btn" data-a="thumbs"></button>
        <span class="pv-sep"></span>
        <button class="icon-btn" data-a="prev"></button>
        <span class="pv-pageno"><input class="pv-pageinput" inputmode="numeric" aria-label="page"><span class="pv-count"></span></span>
        <button class="icon-btn" data-a="next"></button>
        <span class="pv-sep"></span>
        <button class="icon-btn" data-a="out"></button>
        <span class="pv-zoom"></span>
        <button class="icon-btn" data-a="in"></button>
        <button class="icon-btn" data-a="rotate"></button>
        <span class="pv-grow"></span>
        <label class="pv-search"><span class="pv-search-ico"></span><input type="search"><span class="pv-hits"></span></label>
        <button class="icon-btn" data-a="findprev"></button>
        <button class="icon-btn" data-a="findnext"></button>
        <span class="pv-sep"></span>
        <button class="icon-btn" data-a="print"></button>
        <button class="icon-btn" data-a="more"></button>
      </div>
      <div class="pv-main">
        <aside class="pv-thumbs" hidden></aside>
        <div class="pv-scroll" tabindex="0"><div class="pv-pages"></div></div>
      </div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const btn = (a) => el.querySelector(`[data-a="${a}"]`);
  const tools = { thumbs: [icons.sidebar, "pdf.thumbs"], prev: [icons.up, "pdf.prev"], next: [icons.down, "pdf.next"],
    out: [icons.zoomOut, "pdf.zoomOut"], in: [icons.zoomIn, "pdf.zoomIn"], rotate: [icons.rotate, "pdf.rotate"],
    findprev: [icons.up, "pdf.findPrev"], findnext: [icons.down, "pdf.findNext"], print: [icons.print, "pdf.print"],
    more: [icons.more, "pdf.more"] };
  for (const [a, [ico, k]] of Object.entries(tools)) {
    const b = btn(a);
    b.innerHTML = ico;
    b.title = t(k);
    b.setAttribute("aria-label", t(k));
  }
  $(".pv-search-ico").innerHTML = icons.search;
  const search = $(".pv-search input");
  search.placeholder = t("pdf.search");
  const scroller = $(".pv-scroll");
  const pagesEl = $(".pv-pages");
  const thumbsEl = $(".pv-thumbs");

  // ---------- 読み込み ----------
  ctx.setStatus(t("pdf.loading"));
  let doc;
  try {
    doc = await pdfjsLib.getDocument({
      url: `/blob/pdf/${key}`, httpHeaders: { "X-Hub-Token": TOKEN },
      cMapUrl: `${VENDOR}cmaps/`, cMapPacked: true, standardFontDataUrl: `${VENDOR}standard_fonts/`,
      disableRange: true, disableStream: true,
    }).promise;
  } catch (e) {
    ctx.toast(`${t("pdf.loadFailed")}: ${e.message}`, "error", 8000);
    ctx.setStatus("");
    return;
  }
  const N = doc.numPages;
  $(".pv-count").textContent = ` / ${N}`;
  const mb = info.size < 1048576 ? `${Math.max(1, Math.round(info.size / 1024))} KB` : `${(info.size / 1048576).toFixed(info.size > 10485760 ? 0 : 1)} MB`;
  ctx.setStatus(t("pdf.status", { n: N, mb }));

  // ---------- 状態 ----------
  const first = await doc.getPage(1);
  const base = first.getViewport({ scale: 1 });          // 1 ページ目の大きさ（他のページはまず同じと仮定し、読んだら直す）
  const sizes = Array.from({ length: N }, () => ({ w: base.width, h: base.height, known: false }));
  sizes[0].known = true;
  let mode = "width";        // "width"（幅に合わせる）/ "page"（ページ全体）/ "custom"
  let scale = 1;
  let rotation = 0;
  let dark = false;
  let current = 1;
  const rendered = new Map(); // pageIndex → { scale, rotation, task }

  // ---------- ページの器 ----------
  const pageDivs = [];
  for (let i = 0; i < N; i++) {
    const d = document.createElement("div");
    d.className = "pv-page";
    d.dataset.i = i;
    d.innerHTML = `<canvas></canvas><div class="textLayer"></div><span class="pv-pnum">${i + 1}</span>`;
    pagesEl.append(d);
    pageDivs.push(d);
  }

  const dims = (i) => {
    const s = sizes[i];
    const rot = rotation % 180 !== 0;
    return { w: (rot ? s.h : s.w) * scale, h: (rot ? s.w : s.h) * scale };
  };
  function layout() {
    for (let i = 0; i < N; i++) {
      const { w, h } = dims(i);
      pageDivs[i].style.width = `${Math.round(w)}px`;
      pageDivs[i].style.height = `${Math.round(h)}px`;
      pageDivs[i].style.setProperty("--scale-factor", scale);
    }
  }
  function fitScale() {
    const rot = rotation % 180 !== 0;
    const pw = rot ? base.height : base.width;
    const ph = rot ? base.width : base.height;
    const aw = scroller.clientWidth - 40;
    const ah = scroller.clientHeight - 2 * GAP;
    return mode === "page" ? Math.min(aw / pw, ah / ph) : aw / pw;
  }

  // ---------- 描く（見えているページだけ。離れたページは捨ててメモリを節約） ----------
  async function renderPage(i) {
    const r = rendered.get(i);
    if (r && r.scale === scale && r.rotation === rotation) return;
    r?.task?.cancel();
    const div = pageDivs[i];
    const page = await doc.getPage(i + 1);
    if (!sizes[i].known) {
      const v1 = page.getViewport({ scale: 1 });
      sizes[i] = { w: v1.width, h: v1.height, known: true };
      const { w, h } = dims(i);
      div.style.width = `${Math.round(w)}px`;
      div.style.height = `${Math.round(h)}px`;
    }
    const dpr = window.devicePixelRatio || 1;
    const vp = page.getViewport({ scale, rotation });
    const canvas = div.querySelector("canvas");
    const off = document.createElement("canvas");            // 描き終わるまで前の絵を出しておく（ちらつき防止）
    off.width = Math.floor(vp.width * dpr);
    off.height = Math.floor(vp.height * dpr);
    const entry = { scale, rotation, task: null };
    rendered.set(i, entry);
    entry.task = page.render({ canvasContext: off.getContext("2d"), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null });
    try { await entry.task.promise; } catch { return; }       // 拡大し直しなどで取り消された
    if (rendered.get(i) !== entry) return;
    canvas.width = off.width;
    canvas.height = off.height;
    canvas.getContext("2d").drawImage(off, 0, 0);
    canvas.style.width = `${vp.width}px`;
    canvas.style.height = `${vp.height}px`;
    const tl = div.querySelector(".textLayer");
    tl.replaceChildren();
    const layer = new pdfjsLib.TextLayer({ textContentSource: page.streamTextContent(), container: tl, viewport: vp });
    await layer.render().catch(() => {});
    markHits(i);
  }
  function dropPage(i) {
    const r = rendered.get(i);
    if (!r) return;
    r.task?.cancel();
    rendered.delete(i);
    const c = pageDivs[i].querySelector("canvas");
    c.width = c.height = 0;
    pageDivs[i].querySelector(".textLayer").replaceChildren();
  }
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const i = Number(e.target.dataset.i);
      if (e.isIntersecting) renderPage(i);
      else dropPage(i);
    }
  }, { root: scroller, rootMargin: "900px 0px" });
  pageDivs.forEach((d) => io.observe(d));

  function rerender() {
    for (const i of [...rendered.keys()]) rendered.get(i).scale = -1;   // 次に見えたとき描き直す
    for (const d of pageDivs) {
      const r = d.getBoundingClientRect();
      const s = scroller.getBoundingClientRect();
      if (r.bottom > s.top - 900 && r.top < s.bottom + 900) renderPage(Number(d.dataset.i));
    }
  }

  // ---------- 拡大・回転 ----------
  const zoomBox = selectBox({
    options: [{ value: "width", label: t("pdf.fitWidth") }, { value: "page", label: t("pdf.fitPage") },
      ...ZOOMS.map((z) => ({ value: String(z), label: `${Math.round(z * 100)}%` }))],
    value: "width",
    labelFor: (v) => `${Math.round(Number(v) * 100)}%`,
    onChange: (v) => setZoom(v),
  });
  zoomBox.classList.add("pv-zoombox");
  $(".pv-zoom").append(zoomBox);

  function setZoom(v, anchor) {
    const keep = currentAnchor(anchor);
    if (v === "width" || v === "page") { mode = v; scale = fitScale(); }
    else { mode = "custom"; scale = Math.max(0.25, Math.min(6, Number(v))); }
    zoomBox.setValue(mode === "custom" ? String(scale) : mode);
    layout();
    restoreAnchor(keep);
    rerender();
  }
  function step(dir) {
    const cur = scale;
    const next = dir > 0 ? ZOOMS.find((z) => z > cur + 0.01) ?? cur * 1.25 : [...ZOOMS].reverse().find((z) => z < cur - 0.01) ?? cur / 1.25;
    setZoom(String(next));
  }
  // 拡大しても、見ていた場所がずれないようにする
  function currentAnchor() {
    const d = pageDivs[current - 1];
    return { i: current - 1, ratio: (scroller.scrollTop - d.offsetTop) / Math.max(1, d.offsetHeight) };
  }
  function restoreAnchor(a) {
    const d = pageDivs[a.i];
    scroller.scrollTop = d.offsetTop + a.ratio * d.offsetHeight;
  }

  // ---------- ページ送り ----------
  const pageInput = $(".pv-pageinput");
  function goTo(n, smooth = false) {
    n = Math.max(1, Math.min(N, n));
    scroller.scrollTo({ top: pageDivs[n - 1].offsetTop - GAP, behavior: smooth ? "smooth" : "auto" });
  }
  function updateCurrent() {
    const mid = scroller.scrollTop + scroller.clientHeight * 0.35;
    let lo = 0, hi = N - 1;
    while (lo < hi) {                                   // 二分探索（ページが多くても軽い）
      const m = (lo + hi + 1) >> 1;
      if (pageDivs[m].offsetTop <= mid) lo = m; else hi = m - 1;
    }
    if (current !== lo + 1) {
      current = lo + 1;
      if (document.activeElement !== pageInput) pageInput.value = current;
      thumbsEl.querySelectorAll(".pv-thumb").forEach((x) => x.classList.toggle("on", Number(x.dataset.i) === lo));
    }
  }
  scroller.addEventListener("scroll", () => requestAnimationFrame(updateCurrent), { passive: true });
  pageInput.value = 1;
  pageInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { goTo(parseInt(pageInput.value, 10) || 1); scroller.focus(); } });
  pageInput.addEventListener("blur", () => { pageInput.value = current; });

  // ---------- サムネイル ----------
  let thumbsBuilt = false;
  function buildThumbs() {
    thumbsBuilt = true;
    const tio = new IntersectionObserver(async (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting || e.target.dataset.done) continue;
        e.target.dataset.done = "1";
        const i = Number(e.target.dataset.i);
        const page = await doc.getPage(i + 1);
        const v = page.getViewport({ scale: 1, rotation });
        const s = 220 / v.width;                          // 幅 110px × 2（くっきり）
        const vp = page.getViewport({ scale: s, rotation });
        const c = e.target.querySelector("canvas");
        c.width = vp.width; c.height = vp.height;
        await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise.catch(() => {});
      }
    }, { root: thumbsEl, rootMargin: "400px 0px" });
    for (let i = 0; i < N; i++) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pv-thumb";
      b.dataset.i = i;
      b.innerHTML = `<canvas></canvas><span>${i + 1}</span>`;
      b.addEventListener("click", () => goTo(i + 1));
      thumbsEl.append(b);
      tio.observe(b);
    }
  }

  // ---------- 検索（文字の層から探して、見つかった語を光らせる） ----------
  let pageTexts = null;      // 各ページの文字（小文字）
  let hits = [];             // 見つかったページ番号（0 始まり、出現回数ぶん並ぶ）
  let hitPos = -1;
  let query = "";
  async function buildIndex() {
    if (pageTexts) return;
    ctx.setStatus(t("pdf.indexing"));
    pageTexts = [];
    for (let i = 1; i <= N; i++) {
      const tc = await (await doc.getPage(i)).getTextContent();
      pageTexts.push(tc.items.map((it) => it.str).join("").toLowerCase());
    }
    ctx.setStatus(t("pdf.status", { n: N, mb }));
  }
  async function find(dir) {
    const q = search.value.trim().toLowerCase();
    if (!q) { query = ""; hits = []; $(".pv-hits").textContent = ""; pageDivs.forEach((_, i) => markHits(i)); return; }
    if (q !== query) {
      await buildIndex();
      query = q;
      hits = [];
      pageTexts.forEach((txt, i) => { let k = txt.indexOf(q); while (k >= 0) { hits.push(i); k = txt.indexOf(q, k + q.length); } });
      hitPos = hits.findIndex((i) => i >= current - 1) - (dir > 0 ? 1 : 0);
      pageDivs.forEach((_, i) => markHits(i));
    }
    if (!hits.length) { $(".pv-hits").textContent = t("pdf.noHits"); return; }
    hitPos = (hitPos + dir + hits.length) % hits.length;
    $(".pv-hits").textContent = `${hitPos + 1}/${hits.length}`;
    goTo(hits[hitPos] + 1, true);
  }
  function markHits(i) {
    const spans = pageDivs[i].querySelectorAll(".textLayer span");
    spans.forEach((s) => s.classList.toggle("pv-hit", !!query && s.textContent.toLowerCase().includes(query)));
  }
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); find(e.shiftKey ? -1 : 1); }
    if (e.key === "Escape") { search.value = ""; find(1); scroller.focus(); }
  });

  // ---------- 印刷（ページを高い解像度で絵にしてから、印刷の画面を出す） ----------
  async function print() {
    const box = document.createElement("div");
    box.id = "pv-print";
    document.body.append(box);
    const urls = [];
    try {
      for (let i = 1; i <= N; i++) {
        ctx.setStatus(t("pdf.preparing", { i, n: N }));
        const page = await doc.getPage(i);
        const vp = page.getViewport({ scale: 2, rotation });   // 約 144dpi（文字もくっきり）
        const c = document.createElement("canvas");
        c.width = vp.width; c.height = vp.height;
        const g = c.getContext("2d");
        g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
        await page.render({ canvasContext: g, viewport: vp }).promise;
        const blob = await new Promise((r) => c.toBlob(r, "image/png"));
        const url = URL.createObjectURL(blob);
        urls.push(url);
        const img = document.createElement("img");
        img.src = url;
        box.append(img);
      }
      await Promise.all([...box.querySelectorAll("img")].map((im) => im.decode().catch(() => {})));
      ctx.setStatus(t("pdf.status", { n: N, mb }));
      window.print();
    } catch (e) {
      ctx.toast(e.message, "error", 6000);
    } finally {
      setTimeout(() => { box.remove(); urls.forEach((u) => URL.revokeObjectURL(u)); }, 1500);
    }
  }

  // ---------- その他（⋯） ----------
  async function pdfPath() { return ctx.call("reveal_path", { key }); }
  function more(e) {
    const r = btn("more").getBoundingClientRect();
    ctx.contextMenu([
      { label: t("pdf.toText"), icon: icons.text, onClick: toText },
      { label: t("pdf.toImages"), icon: icons.image, onClick: toImages },
      { label: t("pdf.compress"), icon: icons.layers, onClick: () => setTimeout(() => ctx.contextMenu(
        ["light", "standard", "strong"].map((lv) => ({ label: t(`pdf.compress.${lv}`), onClick: () => compress(lv) })), r.left, r.bottom + 4)) },
      "-",
      { label: dark ? t("pdf.lightPages") : t("pdf.darkPages"), icon: icons.moon, onClick: () => { dark = !dark; el.querySelector(".pv").classList.toggle("dark", dark); } },
      { label: t("folders.reveal"), icon: icons.reveal, onClick: async () => ctx.host.revealPath(await pdfPath()).catch((er) => ctx.toast(er.message, "error")) },
    ], r.left, r.bottom + 4);
  }

  // 圧縮する: 隣に「<名前>_圧縮.pdf」を作る（元は変えない）
  async function compress(level) {
    ctx.setStatus(t("pdf.compressing"));
    try {
      const r = await ctx.call("compress", { key, level });
      ctx.setStatus(t("pdf.status", { n: N, mb }));
      const MB = (b) => (b / 1048576).toFixed(b < 10485760 ? 2 : 1);
      if (!r.path) return ctx.toast(t("pdf.compressNoGain", { before: MB(r.before) }), "info", 7000);
      let msg = t("pdf.compressDone", { name: r.name, before: MB(r.before), after: MB(r.after), pct: Math.round((1 - r.after / r.before) * 100) });
      if (r.signed) msg += "\n" + t("pdf.compressSigned");
      ctx.toast(msg, r.signed ? "error" : "info", 9000);
      ctx.host.revealPath(r.path).catch(() => {});
    } catch (e) { ctx.setStatus(""); ctx.toast(e.message, "error", 7000); }
  }

  async function toText() {
    ctx.setStatus(t("pdf.extracting"));
    try {
      const r = await ctx.call("extract_text", { key, pages: "all", ocr: "auto" });
      ctx.setStatus(t("pdf.status", { n: N, mb }));
      let msg = t("pdf.textDone", { name: r.name });
      if (r.ocrPages.length) msg += "\n" + (r.engine ? t("pdf.ocrUsed", { n: r.ocrPages.length, engine: r.engine === "windows" ? "Windows OCR" : "Tesseract" }) : "");
      if (r.unreadPages.length) msg += "\n" + t("pdf.ocrMissing", { pages: r.unreadPages.slice(0, 8).join(", ") });
      ctx.toast(msg.trim(), r.unreadPages.length ? "error" : "info", 8000);
      ctx.host.revealPath(r.path).catch(() => {});
    } catch (e) { ctx.setStatus(""); ctx.toast(e.message, "error", 6000); }
  }

  // 画像にする: manifest の actions（cli.py）をそのまま使う。設定はこの窓の中の小さなシートで
  function toImages() {
    el.querySelector(".pv-sheet")?.remove();
    const action = ctx.module.actions.find((a) => a.id === "to_images");
    const values = Object.fromEntries(action.params.map((p) => [p.name, p.default]));
    const sheet = document.createElement("div");
    sheet.className = "pv-sheet";
    const form = document.createElement("div");
    form.className = "form";
    sheet.append(form);
    function fields() {
      form.replaceChildren();
      const h = document.createElement("div");
      h.className = "pv-sheet-title";
      h.textContent = action.label;
      form.append(h);
      for (const p of action.params) {
        if (p.showIf && Object.entries(p.showIf).some(([k, v]) => values[k] !== v)) continue;
        const f = document.createElement("div");
        f.className = "field";
        const s = document.createElement("span");
        s.textContent = p.label;
        s.id = `pv-${p.name}`;
        let input;
        if (p.type === "select") {
          input = selectBox({ options: p.options.map((o) => (typeof o === "object" ? o : { value: o, label: o })), value: values[p.name],
            labelledBy: s.id, onChange: (v) => { values[p.name] = v; if (action.params.some((q) => q.showIf && p.name in q.showIf)) fields(); } });
        } else {
          input = document.createElement("input");
          input.type = p.type === "number" ? "number" : "text";
          input.value = values[p.name];
          if (p.placeholder) input.placeholder = p.placeholder;
          input.setAttribute("aria-labelledby", s.id);
          input.addEventListener("change", () => { values[p.name] = p.type === "number" ? Number(input.value) : input.value; });
        }
        f.append(s, input);
        form.append(f);
      }
      const row = document.createElement("div");
      row.className = "btn-row";
      const go = document.createElement("button");
      go.className = "btn primary";
      go.type = "button";
      go.textContent = action.label;
      const cancel = document.createElement("button");
      cancel.className = "btn";
      cancel.type = "button";
      cancel.textContent = t("cal.cancel");
      cancel.addEventListener("click", () => sheet.remove());
      go.addEventListener("click", async () => {
        go.disabled = true;
        go.textContent = t("action.running");
        try {
          const r = await api("action", { module: "pdf", action: "to_images", file: await pdfPath(), params: values });
          if (!r.ok) throw new Error((r.stderr || r.stdout || "").trim() || t("common.failed"));
          sheet.remove();
          ctx.toast(t("action.wrote", { n: (r.result?.outputs || []).length }));
          if (r.result?.folder) ctx.host.openPath(r.result.folder).catch(() => {});
        } catch (e) {
          ctx.toast(e.message, "error", 6000);
          go.disabled = false;
          go.textContent = action.label;
        }
      });
      row.append(go, cancel);
      form.append(row);
    }
    fields();
    el.querySelector(".pv").append(sheet);
  }

  // ---------- ボタン・キー ----------
  btn("thumbs").addEventListener("click", () => {
    thumbsEl.hidden = !thumbsEl.hidden;
    btn("thumbs").setAttribute("aria-pressed", String(!thumbsEl.hidden));
    if (!thumbsEl.hidden && !thumbsBuilt) buildThumbs();
    if (mode !== "custom") setZoom(mode);
  });
  btn("prev").addEventListener("click", () => goTo(current - 1, true));
  btn("next").addEventListener("click", () => goTo(current + 1, true));
  btn("out").addEventListener("click", () => step(-1));
  btn("in").addEventListener("click", () => step(1));
  btn("rotate").addEventListener("click", () => {
    rotation = (rotation + 90) % 360;
    thumbsEl.replaceChildren(); thumbsBuilt = false;
    if (!thumbsEl.hidden) buildThumbs();
    setZoom(mode === "custom" ? String(scale) : mode);
  });
  btn("findprev").addEventListener("click", () => find(-1));
  btn("findnext").addEventListener("click", () => find(1));
  btn("print").addEventListener("click", print);
  btn("more").addEventListener("click", more);

  // ---- 文字のコピー（文字が埋め込まれた PDF だけ。スキャンした PDF は「その他 → 文字にする」で OCR） ----
  // 日本語の字と字の間に入る余計な空白を取ってからクリップボードへ
  const CJK = "\\u3000-\\u30ff\\u3400-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef";
  const tidy = (s) => s.replace(new RegExp(`(?<=[${CJK}]) +(?=[${CJK}])`, "g"), "");
  const selectedText = () => {
    const sel = getSelection();
    return sel && !sel.isCollapsed && scroller.contains(sel.anchorNode) ? tidy(sel.toString()) : "";
  };
  document.addEventListener("copy", (e) => {
    const s = selectedText();
    if (!s) return;
    e.preventDefault();
    e.clipboardData.setData("text/plain", s);
  });
  scroller.addEventListener("contextmenu", (e) => {
    const s = selectedText();
    if (!s) return;
    e.preventDefault();
    ctx.contextMenu([{ label: t("set.copy"), icon: icons.copy || icons.text, onClick: async () => {
      try { await navigator.clipboard.writeText(s); ctx.toast(t("web.copied")); } catch { document.execCommand("copy"); }
    } }], e.clientX, e.clientY);
  });

  document.addEventListener("keydown", (e) => {
    const typing = e.target.matches?.("input, textarea");
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "a" && !typing) {        // Ctrl+A: 今のページの文字をすべて選ぶ（画面のボタンなどは選ばない）
      e.preventDefault();
      const tl = pageDivs[current - 1]?.querySelector(".textLayer");
      if (tl?.childNodes.length) getSelection().selectAllChildren(tl);
      return;
    }
    if (mod && e.key.toLowerCase() === "f") { e.preventDefault(); search.focus(); search.select(); return; }
    if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); print(); return; }
    if (mod && (e.key === "+" || e.key === "=" || e.key === ";")) { e.preventDefault(); step(1); return; }
    if (mod && e.key === "-") { e.preventDefault(); step(-1); return; }
    if (mod && e.key === "0") { e.preventDefault(); setZoom("width"); return; }
    if (typing) return;
    if (e.key === "PageDown" || e.key === "ArrowRight") { e.preventDefault(); goTo(current + 1); }
    if (e.key === "PageUp" || e.key === "ArrowLeft") { e.preventDefault(); goTo(current - 1); }
    if (e.key === "Home") { e.preventDefault(); goTo(1); }
    if (e.key === "End") { e.preventDefault(); goTo(N); }
  });
  scroller.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    step(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  // 窓の大きさが変わったら、幅合わせ・ページ全体のときは合わせ直す
  let rt = null;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (mode !== "custom") setZoom(mode); }, 120); }).observe(scroller);

  // 別の PDF をこの窓に落としたら、新しい窓で開く
  ctx.onNativeDrop(async (paths) => {
    for (const p of paths.filter((x) => /\.(pdf|png|jpe?g|jpe|jfif|gif|webp|bmp|tiff?)$/i.test(x))) {
      try { const r = await ctx.call("open_doc", { path: p }); await ctx.host.openPanel(r.panel); }
      catch (er) { ctx.toast(er.message, "error"); }
    }
  });
  el.addEventListener("dragover", (e) => e.preventDefault());
  el.addEventListener("drop", (e) => e.preventDefault());

  scale = fitScale();
  layout();
  rerender();
  scroller.focus();
}
