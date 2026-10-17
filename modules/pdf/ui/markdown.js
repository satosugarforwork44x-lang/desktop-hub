// pdf/ui/markdown.js — 文章の窓（Markdown・テキスト・RTF）。「読む」と「書く」を切り替える。
//   ・読む: md は marked（MIT、vendor/marked）で表示。md の中の HTML は動かさず文字として出す（Claude が書いた md も安全に）
//           txt・rtf はそのまま（rtf は文字だけ）。外で書き換えられたら自動で読み直す
//   ・書く: 紙の上でそのまま打つ（md・txt だけ。rtf は書式を壊すので読むだけ）。少し待つと自動で保存。
//           外で書き換えられていたら上書きせず、どちらを残すか聞く
//   ・紙: 無地・罫線・方眼（ファイルごとに覚える）
//   ・リンク: Web は既定のブラウザ、#見出し は窓の中、ほかのファイルは Hub で開けるものは Hub、それ以外は関連付けたアプリ
//   ・画像: md の横に置いた写真・手書き（相対パス）は表示する。Web の画像は読み込まない（外への通信をしない）
//   ・写真・手書き（md だけ）: 貼る・選ぶ・手書きの板で描く → md の横の「<名前>_files」に保存して ![](…) を差し込む
import { marked } from "./vendor/marked/marked.esm.js";
import { icons } from "/ui/js/icons.js";
import { TOKEN } from "/ui/js/hub.js";
import { inkPad } from "./ink.js";
import { OPENS } from "./panel.js";

const ZOOMS = [0.85, 0.92, 1, 1.1, 1.2, 1.35, 1.5];
const PAPERS = ["plain", "lined", "grid"];
const POLL_MS = 2000;
const LOCAL_PIC = /^(?![a-z][a-z0-9+.-]*:)(?!\/)[^?#]+\.(png|jpe?g|gif|webp|svg)$/i;   // md から見た相対パスの画像
let current = { key: "", v: 0 };       // 表示中の文書（画像の URL を作るため）
const SAVE_MS = 1200;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const slug = (s) => s.toLowerCase().trim().replace(/<[^>]+>/g, "").replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* 保存できなくても表示はできる */ } },
  take(k) { try { const v = localStorage.getItem(k); localStorage.removeItem(k); return v; } catch { return null; } },
};

// md の中の HTML は文字として表示する・画像は読み込まずにボタンにする・見出しに id を付ける（目次のリンク用）
marked.use({
  gfm: true,
  breaks: true,          // メモとして読むので、1 回の改行もそのまま改行にする
  renderer: {
    html({ text }) { return esc(text); },
    image({ href, text }) {
      if (LOCAL_PIC.test(href) && !decodeURIComponent(href).split(/[\\/]/).includes("..")) {
        const src = `/blob/pdf/${current.key}/a/${href.split("/").map((x) => encodeURIComponent(decodeURIComponent(x))).join("/")}?t=${encodeURIComponent(TOKEN)}&v=${current.v}`;
        const ink = /(^|\/)ink-[^/]*\.svg$/i.test(href) ? " md-ink" : "";
        return `<a class="md-pic${ink}" href="${esc(href)}" title="${esc(text || href)}"><img src="${esc(src)}" alt="${esc(text)}" loading="lazy"></a>`;
      }
      return `<a class="md-img" href="${esc(href)}" title="${esc(href)}">${icons.image}<span>${esc(text || href)}</span></a>`;
    },
    heading({ tokens, depth }) {
      const inner = this.parser.parseInline(tokens);
      return `<h${depth} id="${esc(slug(inner))}">${inner}</h${depth}>\n`;
    },
  },
});

// md のある場所から見た相対パスを、フルパスにする（Windows の \ と / の両方）
function resolve(folder, href) {
  const sep = folder.includes("\\") ? "\\" : "/";
  const parts = folder.split(/[\\/]/);
  for (const p of decodeURIComponent(href.split("#")[0]).split(/[\\/]/)) {
    if (p === "..") parts.pop();
    else if (p && p !== ".") parts.push(p);
  }
  return parts.join(sep);
}

export async function mount(el, ctx) {
  const t = ctx.t;
  const key = ctx.instance;
  for (const f of ["./pdf.css", "./markdown.css"]) {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = new URL(f, import.meta.url).href;
    document.head.append(css);
  }

  el.innerHTML = `
    <div class="pv md">
      <div class="pv-bar">
        <button class="icon-btn" data-a="out"></button>
        <span class="pv-zoom"></span>
        <button class="icon-btn" data-a="in"></button>
        <span class="pv-sep"></span>
        <button class="icon-btn" data-a="paper"></button>
        <span class="pv-grow"></span>
        <span class="md-state"></span>
        <button class="icon-btn md-w" data-a="photo" hidden></button>
        <button class="icon-btn md-w" data-a="ink" hidden></button>
        <button class="btn md-mode" data-a="mode" hidden></button>
        <button class="btn md-rtf" data-a="rtf" hidden></button>
        <button class="icon-btn" data-a="edit"></button>
        <button class="icon-btn" data-a="reveal"></button>
      </div>
      <div class="md-conflict" hidden>
        <span></span>
        <button class="btn" data-a="theirs"></button>
        <button class="btn primary" data-a="mine"></button>
      </div>
      <div class="md-scroll" tabindex="0"><article class="md-body"></article></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const scroller = $(".md-scroll");
  const body = $(".md-body");
  const stateEl = $(".md-state");
  const modeBtn = $(".md-mode");
  const tools = { out: [icons.zoomOut, t("pdf.zoomOut")], in: [icons.zoomIn, t("pdf.zoomIn")], paper: [icons.layers, t("md.paper")],
    edit: [icons.open, t("md.openWith")], reveal: [icons.reveal, t("folders.reveal")],
    photo: [icons.image, t("md.photo")], ink: [icons.edit, t("md.ink")] };
  for (const [a, [icon, label]] of Object.entries(tools)) {
    const b = el.querySelector(`[data-a="${a}"]`);
    b.innerHTML = icon;
    b.title = label;
    b.setAttribute("aria-label", label);
  }
  $('[data-a="theirs"]').textContent = t("md.useTheirs");
  $('[data-a="mine"]').textContent = t("md.useMine");
  $(".md-conflict span").textContent = t("md.conflict");

  // ---- 文字の大きさ（窓をまたいで覚える） ----
  let zi = Math.max(0, Math.min(ZOOMS.length - 1, Number(store.get("hub.md.zoom", 2))));
  function zoom(step) {
    zi = Math.max(0, Math.min(ZOOMS.length - 1, step === 0 ? 2 : zi + step));
    applyZoom();
  }
  function applyZoom() {
    body.style.setProperty("--md-scale", ZOOMS[zi]);
    $(".pv-zoom").textContent = `${Math.round(ZOOMS[zi] * 100)}%`;
    store.set("hub.md.zoom", String(zi));
  }

  // ---- 紙（無地・罫線・方眼）。ファイルごとに覚える。初めてのファイルは前回選んだ紙 ----
  let doc = null;      // { text, mtime, folder, path, kind, writable }
  const paperKey = () => `hub.md.paper:${doc?.path || key}`;
  function applyPaper(p) {
    body.dataset.paper = PAPERS.includes(p) ? p : "plain";
    $('[data-a="paper"]').title = `${t("md.paper")}: ${t(`md.paper.${body.dataset.paper}`)}`;
  }
  $('[data-a="paper"]').addEventListener("click", (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    ctx.contextMenu(PAPERS.map((p) => ({
      label: `${body.dataset.paper === p ? "✓ " : ""}${t(`md.paper.${p}`)}`,
      onClick: () => { applyPaper(p); store.set(paperKey(), p); store.set("hub.md.paper", p); },
    })), r.left, r.bottom + 4);
  });

  // ---- 読む ----
  function renderRead() {
    current = { key, v: doc.mtime };
    if (doc.kind === "md") body.innerHTML = marked.parse(doc.text);
    else body.innerHTML = `<div class="md-plain">${esc(doc.text)}</div>`;
    for (const a of body.querySelectorAll("a[href]")) a.title ||= a.getAttribute("href");
  }
  async function load(keepScroll = false) {
    const top = scroller.scrollTop;
    try {
      doc = await ctx.call("read_text", { key });
    } catch (e) {
      body.innerHTML = `<p class="md-error"></p>`;
      body.querySelector(".md-error").textContent = e.message;
      return;
    }
    applyPaper(store.get(paperKey(), store.get("hub.md.paper", "plain")));
    modeBtn.hidden = !doc.writable;
    const rtfBtn = $('[data-a="rtf"]');
    rtfBtn.hidden = doc.kind !== "rtf";
    if (doc.rtfEdit) {
      rtfBtn.textContent = t(`md.rtf.${doc.rtfEdit}`);
      rtfBtn.title = t(`md.rtf.${doc.rtfEdit}Tip`);
    }
    if (writing) { editor.value = doc.text; dirty = false; setState(""); }
    else renderRead();
    ctx.setStatus(doc.path);
    ctx.setTitle(doc.path.split(/[\\/]/).pop());
    if (keepScroll) scroller.scrollTop = top;
  }

  // ---- 書く（紙の上でそのまま打つ。少し待つと自動で保存） ----
  let writing = false, dirty = false, saveTimer = null, saving = null;
  const editor = document.createElement("textarea");
  editor.className = "md-edit";
  editor.spellcheck = false;
  editor.setAttribute("aria-label", t("md.write"));
  const grow = () => { editor.style.height = "auto"; editor.style.height = `${editor.scrollHeight}px`; };
  function setState(s) { stateEl.textContent = s ? t(`md.state.${s}`) : ""; stateEl.dataset.s = s; }
  function setMode(on) {
    if (on && !doc?.writable) return;
    if (!on && dirty) save();
    writing = on;
    el.querySelector(".pv").classList.toggle("writing", on);
    for (const b of el.querySelectorAll(".md-w")) b.hidden = !on || doc.kind !== "md";   // 写真・手書きは md だけ
    modeBtn.textContent = on ? t("md.read") : t("md.write");
    modeBtn.classList.toggle("primary", !on);
    if (on) {
      body.replaceChildren(editor);
      editor.value = doc.text;
      grow();
      editor.focus();
    } else {
      setState("");
      renderRead();
      scroller.focus();
    }
  }
  async function save(force = false) {
    clearTimeout(saveTimer);
    if (!dirty || !doc) return;
    if (saving) { await saving; if (!dirty) return; }
    const text = editor.value;
    setState("saving");
    saving = ctx.call("write_text", { key, text, base_mtime: force ? -1 : doc.mtime })
      .catch((e) => { ctx.toast(e.message, "error", 6000); return null; });
    let r = await saving;
    saving = null;
    if (r?.conflict && force) {                  // 「自分の版で上書き」: いまの更新時刻で書き直す
      saving = ctx.call("write_text", { key, text, base_mtime: r.mtime });
      r = await saving.catch(() => null);
      saving = null;
    }
    if (!r) { setState("error"); return; }
    if (r.conflict) { setState("conflict"); $(".md-conflict").hidden = false; return; }
    doc.text = text;
    doc.mtime = r.mtime;
    if (editor.value === text) { dirty = false; setState("saved"); }
  }
  editor.addEventListener("input", () => {
    dirty = true;
    setState("editing");
    grow();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(), SAVE_MS);
  });
  $('[data-a="theirs"]').addEventListener("click", async () => { $(".md-conflict").hidden = true; dirty = false; await load(true); });
  $('[data-a="mine"]').addEventListener("click", async () => { $(".md-conflict").hidden = true; dirty = true; await save(true); });
  modeBtn.addEventListener("click", () => setMode(!writing));
  // rtf を直す: LibreOffice / Word があればそれで開く。無ければ txt の写しを作って、新しい窓で開く（元の rtf は変えない）
  $('[data-a="rtf"]').addEventListener("click", async () => {
    try {
      const r = await ctx.call("rtf_edit", { key });
      if (r.mode !== "txt") return ctx.toast(t(`md.rtf.opened`), "info", 4000);
      const w = await ctx.host.openFile(r.path);
      if (!ctx.isNative() && w?.url) window.open(w.url, w.id, "width=880,height=1000");
      ctx.toast(t("md.rtf.copied", { name: r.path.split(/[\\/]/).pop() }), "info", 6000);
    } catch (e) { ctx.toast(e.message, "error", 6000); }
  });

  // ---- 写真・手書き（md だけ。txt には絵を入れられないので案内する） ----
  function insertAtCaret(md) {
    const s = editor.selectionStart, e = editor.selectionEnd;
    const before = editor.value.slice(0, s);
    const pre = before && !before.endsWith("\n") ? "\n" : "";
    editor.setRangeText(`${pre}${md}\n`, s, e, "end");
    editor.dispatchEvent(new Event("input"));
    editor.focus();
  }
  async function addPicture(blob, ext, kind) {
    if (doc.kind !== "md") return ctx.toast(t("md.mdOnly"), "error", 5000);
    try {
      setState("saving");
      const r = await ctx.upload("save_asset", blob, { key, ext, kind });
      insertAtCaret(`![${kind === "ink" ? t("md.ink") : t("md.photo")}](<${r.rel}>)`);   // <…> で囲むと、空白や日本語の名前もそのまま書ける
    } catch (e) { setState("error"); ctx.toast(e.message, "error", 5000); }
  }
  const extOf = (f) => (f.type.split("/")[1] || f.name.split(".").pop() || "png").replace("jpeg", "jpg").replace("svg+xml", "svg");
  const picker = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: true, hidden: true });
  el.append(picker);
  picker.addEventListener("change", async () => { for (const f of picker.files) await addPicture(f, extOf(f), "img"); picker.value = ""; });
  $('[data-a="photo"]').addEventListener("click", () => (doc.kind === "md" ? picker.click() : ctx.toast(t("md.mdOnly"), "error", 5000)));
  $('[data-a="ink"]').addEventListener("click", async () => {
    if (doc.kind !== "md") return ctx.toast(t("md.mdOnly"), "error", 5000);
    const svg = await inkPad(el, t);
    if (svg) await addPicture(new Blob([svg], { type: "image/svg+xml" }), "svg", "ink");
  });
  editor.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;
    e.preventDefault();
    files.reduce((p, f) => p.then(() => addPicture(f, extOf(f), "img")), Promise.resolve());
  });
  addEventListener("beforeunload", () => { if (dirty) save(); });

  // ---- リンクは窓の中で移動させず、行き先ごとに開き方を変える ----
  body.addEventListener("click", async (e) => {
    const a = e.target.closest("a[href]");
    if (!a || writing) return;
    e.preventDefault();
    const href = a.getAttribute("href");
    try {
      if (/^(https?:|mailto:)/i.test(href)) return void await ctx.host.openUrl(href);
      if (href.startsWith("#")) return void body.querySelector(`[id="${CSS.escape(decodeURIComponent(href.slice(1)))}"]`)?.scrollIntoView({ behavior: "smooth" });
      if (/^[a-z][a-z0-9+.-]*:/i.test(href) && !/^[a-z]:[\\/]/i.test(href)) return;   // ほかの種類のリンク（javascript: など）は開かない
      const full = /^([a-z]:)?[\\/]/i.test(href) ? decodeURIComponent(href) : resolve(doc.folder, href);
      if (OPENS.test(full)) {
        const w = await ctx.host.openFile(full);
        if (!ctx.isNative() && w?.url) window.open(w.url, w.id, "width=880,height=1000");
      } else await ctx.host.openPath(full);
    } catch (er) { ctx.toast(er.message, "error", 5000); }
  });

  $('[data-a="out"]').addEventListener("click", () => zoom(-1));
  $('[data-a="in"]').addEventListener("click", () => zoom(1));
  $('[data-a="edit"]').addEventListener("click", async () => { await save(); doc && ctx.host.openPath(doc.path).catch((e) => ctx.toast(e.message, "error")); });
  $('[data-a="reveal"]').addEventListener("click", () => doc && ctx.host.revealPath(doc.path).catch((e) => ctx.toast(e.message, "error")));
  el.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "e" && doc?.writable) { e.preventDefault(); setMode(!writing); return; }
    if (e.ctrlKey && (e.key === "+" || e.key === ";" || e.key === "=")) { e.preventDefault(); zoom(1); }
    if (e.ctrlKey && e.key === "-") { e.preventDefault(); zoom(-1); }
    if (e.ctrlKey && e.key === "0") { e.preventDefault(); zoom(0); }
    if (e.key === "F5" && !writing) { e.preventDefault(); load(true); }
  });
  scroller.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); zoom(e.deltaY < 0 ? 1 : -1); } }, { passive: false });
  addEventListener("resize", () => writing && grow());

  // 外で書き換えられたら読み直す（Claude が書き直したときなど）。書いている途中なら上書きせず、保存のときに聞く
  setInterval(async () => {
    if (!doc || document.visibilityState !== "visible" || saving) return;
    const m = await ctx.call("mtime", { key }).catch(() => null);
    if (m && m !== doc.mtime && !dirty) load(true);
  }, POLL_MS);

  applyZoom();
  await load();
  modeBtn.textContent = t("md.write");
  modeBtn.classList.add("primary");
  // 「新しいメモ」から開いたときは、すぐに書ける状態で
  if (doc && store.take(`hub.md.write:${doc.path}`)) setMode(true);
  else scroller.focus();
}
