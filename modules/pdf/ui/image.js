// pdf/ui/image.js — 画像ビューア（PNG / JPEG / GIF / WebP / BMP / TIFF）。1 つの窓で同じフォルダの画像を順に見られる。
//   全体表示・実寸・拡大縮小（Ctrl+ホイール）・ドラッグで移動・回転・背景の切り替え・複数ページの TIFF・印刷・文字の読み取り（OCR）
import { selectBox, TOKEN } from "/ui/js/hub.js";
import { icons } from "/ui/js/icons.js";
import { OPENS } from "./panel.js";

const ZOOMS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 8];
const BGS = ["checker", "dark", "light"];

export async function mount(el, ctx) {
  const t = ctx.t;
  let key = ctx.instance;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./pdf.css", import.meta.url).href;
  document.head.append(css);

  el.innerHTML = `
    <div class="pv iv">
      <div class="pv-bar">
        <button class="icon-btn" data-a="prevImg"></button>
        <span class="iv-pos"></span>
        <button class="icon-btn" data-a="nextImg"></button>
        <span class="iv-pages" hidden>
          <span class="pv-sep"></span>
          <button class="icon-btn" data-a="prevPage"></button>
          <span class="iv-page"></span>
          <button class="icon-btn" data-a="nextPage"></button>
        </span>
        <span class="pv-sep"></span>
        <button class="icon-btn" data-a="out"></button>
        <span class="pv-zoom"></span>
        <button class="icon-btn" data-a="in"></button>
        <button class="icon-btn" data-a="rotate"></button>
        <span class="pv-grow"></span>
        <button class="icon-btn" data-a="bg"></button>
        <button class="icon-btn" data-a="print"></button>
        <button class="icon-btn" data-a="more"></button>
      </div>
      <div class="iv-scroll" tabindex="0"><div class="iv-stage"><img class="iv-img" alt="" draggable="false"></div></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const btn = (a) => el.querySelector(`[data-a="${a}"]`);
  const tools = { prevImg: [icons.left, "img.prev"], nextImg: [icons.right, "img.next"], prevPage: [icons.up, "img.prevPage"],
    nextPage: [icons.down, "img.nextPage"], out: [icons.zoomOut, "pdf.zoomOut"], in: [icons.zoomIn, "pdf.zoomIn"],
    rotate: [icons.rotate, "pdf.rotate"], bg: [icons.moon, "img.bg"], print: [icons.print, "pdf.print"], more: [icons.more, "pdf.more"] };
  for (const [a, [ico, k]] of Object.entries(tools)) {
    const b = btn(a);
    b.innerHTML = ico;
    b.title = t(k);
    b.setAttribute("aria-label", t(k));
  }
  const scroller = $(".iv-scroll");
  const stage = $(".iv-stage");
  const img = $(".iv-img");

  let info = null;
  let page = 1;
  let mode = "fit";         // "fit" / "custom"
  let scale = 1;
  let rotation = 0;
  let bg = 0;
  try { bg = Math.max(0, BGS.indexOf(localStorage.getItem("hub.viewer.bg") || "checker")); } catch { /* 保存できない環境 */ }

  // ---------- 拡大 ----------
  const zoomBox = selectBox({
    options: [{ value: "fit", label: t("img.fit") }, ...ZOOMS.map((z) => ({ value: String(z), label: `${Math.round(z * 100)}%` }))],
    value: "fit",
    labelFor: (v) => `${Math.round(Number(v) * 100)}%`,
    onChange: (v) => setZoom(v),
  });
  zoomBox.classList.add("pv-zoombox");
  $(".pv-zoom").append(zoomBox);

  const natural = () => {
    const w = img.naturalWidth || info?.width || 1, h = img.naturalHeight || info?.height || 1;
    return rotation % 180 ? { w: h, h: w } : { w, h };
  };
  function fitScale() {
    const n = natural();
    return Math.min(1, (scroller.clientWidth - 32) / n.w, (scroller.clientHeight - 32) / n.h);   // 小さい画像は引き伸ばさない
  }
  function layout(anchor) {
    if (mode === "fit") scale = fitScale();
    const n = natural();
    const W = Math.max(1, Math.round(n.w * scale)), H = Math.max(1, Math.round(n.h * scale));
    // 回転は img を回し、外枠（stage）は回したあとの大きさにする
    const iw = rotation % 180 ? H : W, ih = rotation % 180 ? W : H;
    stage.style.width = `${W}px`;
    stage.style.height = `${H}px`;
    img.style.width = `${iw}px`;
    img.style.height = `${ih}px`;
    img.style.transform = `translate(-50%, -50%) rotate(${rotation}deg)`;
    zoomBox.setValue(mode === "fit" ? "fit" : String(scale));
    img.style.imageRendering = scale >= 2 ? "pixelated" : "auto";   // 大きく拡大したときは画素をくっきり
    if (anchor) {
      scroller.scrollLeft = anchor.x * stage.offsetWidth - anchor.cx;
      scroller.scrollTop = anchor.y * stage.offsetHeight - anchor.cy;
    }
  }
  // 拡大しても、指している場所（無ければ真ん中）がずれないようにする
  function anchorAt(cx = scroller.clientWidth / 2, cy = scroller.clientHeight / 2) {
    const r = stage.getBoundingClientRect(), s = scroller.getBoundingClientRect();
    return { x: (s.left + cx - r.left) / Math.max(1, r.width), y: (s.top + cy - r.top) / Math.max(1, r.height), cx, cy };
  }
  function setZoom(v, anchor) {
    const a = anchor || anchorAt();
    if (v === "fit") mode = "fit";
    else { mode = "custom"; scale = Math.max(0.05, Math.min(16, Number(v))); }
    layout(mode === "fit" ? null : a);
  }
  function step(dir, anchor) {
    const cur = scale;
    const next = dir > 0 ? ZOOMS.find((z) => z > cur + 0.001) ?? cur * 1.25 : [...ZOOMS].reverse().find((z) => z < cur - 0.001) ?? cur / 1.25;
    setZoom(String(next), anchor);
  }

  // ---------- 読み込み ----------
  const blobUrl = () => `/blob/pdf/${key}${info?.pages > 1 ? `/${page}` : ""}?t=${encodeURIComponent(TOKEN)}&v=${info?.mtime || 0}`;
  async function load(newKey, pos) {
    key = newKey;
    try { info = await ctx.call("doc_info", { key }); }
    catch (e) { ctx.toast(e.message, "error", 6000); return; }
    page = 1;
    rotation = 0;
    mode = "fit";
    ctx.setTitle(info.name);
    $(".iv-pos").textContent = pos ? t("img.pos", { i: pos.index, n: pos.count }) : "";
    $(".iv-pages").hidden = !(info.pages > 1);
    await show();
  }
  async function show() {
    $(".iv-page").textContent = info.pages > 1 ? t("img.pos", { i: page, n: info.pages }) : "";
    img.src = blobUrl();
    try { await img.decode(); }
    catch { ctx.toast(t("img.failed"), "error", 6000); }
    layout();
    const mb = info.size < 1048576 ? `${Math.max(1, Math.round(info.size / 1024))} KB` : `${(info.size / 1048576).toFixed(1)} MB`;
    ctx.setStatus(t("img.status", { w: info.width || img.naturalWidth, h: info.height || img.naturalHeight, fmt: info.format || "", mb }));
  }
  async function go(stepDir) {
    try {
      const r = await ctx.call("neighbor", { key, step: stepDir });
      await load(r.key, r);
    } catch (e) { ctx.toast(e.message, "error"); }
  }
  function goPage(d) {
    const p = Math.max(1, Math.min(info.pages, page + d));
    if (p !== page) { page = p; show(); }
  }

  // ---------- 背景 ----------
  function applyBg() {
    el.querySelector(".iv").dataset.bg = BGS[bg];
    try { localStorage.setItem("hub.viewer.bg", BGS[bg]); } catch { /* 同上 */ }
  }

  // ---------- 印刷（回転していればその向きで） ----------
  async function print() {
    const box = document.createElement("div");
    box.id = "pv-print";
    document.body.append(box);
    let url = img.src;
    let made = null;
    if (rotation) {
      const c = document.createElement("canvas");
      const w = img.naturalWidth, h = img.naturalHeight;
      c.width = rotation % 180 ? h : w;
      c.height = rotation % 180 ? w : h;
      const g = c.getContext("2d");
      g.translate(c.width / 2, c.height / 2);
      g.rotate((rotation * Math.PI) / 180);
      g.drawImage(img, -w / 2, -h / 2);
      made = URL.createObjectURL(await new Promise((r) => c.toBlob(r, "image/png")));
      url = made;
    }
    const p = document.createElement("img");
    p.src = url;
    box.append(p);
    await p.decode().catch(() => {});
    window.print();
    setTimeout(() => { box.remove(); if (made) URL.revokeObjectURL(made); }, 1500);
  }

  // ---------- その他（⋯） ----------
  async function toText() {
    ctx.setStatus(t("pdf.extracting"));
    try {
      const r = await ctx.call("extract_text", { key, pages: "all" });
      let msg = t("pdf.textDone", { name: r.name });
      if (r.unreadPages.length) msg += "\n" + t("pdf.ocrMissing", { pages: r.unreadPages.slice(0, 8).join(", ") });
      ctx.toast(msg, r.unreadPages.length ? "error" : "info", 8000);
      ctx.host.revealPath(r.path).catch(() => {});
    } catch (e) { ctx.toast(e.message, "error", 6000); }
    show();
  }
  function more() {
    const r = btn("more").getBoundingClientRect();
    ctx.contextMenu([
      { label: t("img.toText"), icon: icons.text, onClick: toText },
      { label: t("img.actual"), icon: icons.zoomIn, onClick: () => setZoom("1") },
      "-",
      { label: t("folders.reveal"), icon: icons.reveal, onClick: async () => ctx.host.revealPath(await ctx.call("reveal_path", { key })).catch((er) => ctx.toast(er.message, "error")) },
    ], r.left, r.bottom + 4);
  }

  // ---------- ボタン・キー・マウス ----------
  btn("prevImg").addEventListener("click", () => go(-1));
  btn("nextImg").addEventListener("click", () => go(1));
  btn("prevPage").addEventListener("click", () => goPage(-1));
  btn("nextPage").addEventListener("click", () => goPage(1));
  btn("out").addEventListener("click", () => step(-1));
  btn("in").addEventListener("click", () => step(1));
  btn("rotate").addEventListener("click", () => { rotation = (rotation + 90) % 360; layout(); });
  btn("bg").addEventListener("click", () => { bg = (bg + 1) % BGS.length; applyBg(); });
  btn("print").addEventListener("click", print);
  btn("more").addEventListener("click", more);

  document.addEventListener("keydown", (e) => {
    if (e.target.closest?.(".menu")) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); print(); return; }
    if (mod && (e.key === "+" || e.key === "=" || e.key === ";")) { e.preventDefault(); step(1); return; }
    if (mod && e.key === "-") { e.preventDefault(); step(-1); return; }
    if (mod && e.key === "0") { e.preventDefault(); setZoom("fit"); return; }
    if (mod) return;
    if (e.key === "ArrowRight" && mode === "fit") { e.preventDefault(); go(1); }
    else if (e.key === "ArrowLeft" && mode === "fit") { e.preventDefault(); go(-1); }
    else if (e.key === "PageDown") { e.preventDefault(); info.pages > 1 ? goPage(1) : go(1); }
    else if (e.key === "PageUp") { e.preventDefault(); info.pages > 1 ? goPage(-1) : go(-1); }
    else if (e.key.toLowerCase() === "r") { rotation = (rotation + 90) % 360; layout(); }
    else if (e.key === "1") setZoom("1");
  });
  scroller.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const s = scroller.getBoundingClientRect();
    step(e.deltaY < 0 ? 1 : -1, anchorAt(e.clientX - s.left, e.clientY - s.top));
  }, { passive: false });
  // ダブルクリック: 全体 ⇄ 実寸（押した場所を中心に）
  scroller.addEventListener("dblclick", (e) => {
    const s = scroller.getBoundingClientRect();
    setZoom(mode === "fit" ? "1" : "fit", anchorAt(e.clientX - s.left, e.clientY - s.top));
  });
  // ドラッグで移動（はみ出しているとき）
  scroller.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || scroller.scrollWidth <= scroller.clientWidth && scroller.scrollHeight <= scroller.clientHeight) return;
    const sx = e.clientX, sy = e.clientY, l = scroller.scrollLeft, tp = scroller.scrollTop;
    scroller.setPointerCapture(e.pointerId);
    scroller.classList.add("dragging");
    const move = (ev) => { scroller.scrollLeft = l - (ev.clientX - sx); scroller.scrollTop = tp - (ev.clientY - sy); };
    const up = () => { scroller.classList.remove("dragging"); scroller.removeEventListener("pointermove", move); scroller.removeEventListener("pointerup", up); };
    scroller.addEventListener("pointermove", move);
    scroller.addEventListener("pointerup", up);
  });
  let rt = null;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (mode === "fit") layout(); }, 80); }).observe(scroller);

  // 別のファイルをこの窓に落としたら、新しい窓で開く
  ctx.onNativeDrop(async (paths) => {
    for (const p of paths.filter((x) => OPENS.test(x))) {
      try { const r = await ctx.call("open_doc", { path: p }); await ctx.host.openPanel(r.panel); }
      catch (er) { ctx.toast(er.message, "error"); }
    }
  });
  el.addEventListener("dragover", (e) => e.preventDefault());
  el.addEventListener("drop", (e) => e.preventDefault());

  applyBg();
  await load(key, null);
  scroller.focus();
}
