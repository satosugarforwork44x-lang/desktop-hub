// pdf/ui/markdown.js — Markdown を読むための窓（読むだけ。直すときは関連付けたアプリで開く）。
//   ・表示は marked（MIT、vendor/marked）。md の中の HTML は動かさず文字として出す（Claude が書いた md も安全に読めるように）
//   ・外で書き換えられたら自動で読み直す（スクロール位置はそのまま）
//   ・リンク: Web は既定のブラウザ、#見出し は窓の中、ほかのファイルは Hub で開けるものは Hub、それ以外は関連付けたアプリ
//   ・画像は読み込まない（外への通信をしない）。押すと Hub のビューアで開く
import { marked } from "./vendor/marked/marked.esm.js";
import { icons } from "/ui/js/icons.js";
import { OPENS } from "./panel.js";

const ZOOMS = [0.85, 0.92, 1, 1.1, 1.2, 1.35, 1.5];
const POLL_MS = 2000;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const slug = (s) => s.toLowerCase().trim().replace(/<[^>]+>/g, "").replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");

// md の中の HTML は文字として表示する・画像は読み込まずにボタンにする・見出しに id を付ける（目次のリンク用）
marked.use({
  gfm: true,
  renderer: {
    html({ text }) { return esc(text); },
    image({ href, text }) {
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
        <span class="pv-grow"></span>
        <button class="icon-btn" data-a="edit"></button>
        <button class="icon-btn" data-a="reveal"></button>
      </div>
      <div class="md-scroll" tabindex="0"><article class="md-body"></article></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const scroller = $(".md-scroll");
  const body = $(".md-body");
  const tools = { out: [icons.zoomOut, t("pdf.zoomOut")], in: [icons.zoomIn, t("pdf.zoomIn")],
    edit: [icons.edit, t("md.openWith")], reveal: [icons.reveal, t("folders.reveal")] };
  for (const [a, [icon, label]] of Object.entries(tools)) {
    const b = el.querySelector(`[data-a="${a}"]`);
    b.innerHTML = icon;
    b.title = label;
    b.setAttribute("aria-label", label);
  }

  // 文字の大きさ（窓をまたいで覚える）
  let zi = 2;
  try { zi = Math.max(0, Math.min(ZOOMS.length - 1, Number(localStorage.getItem("hub.md.zoom") ?? 2))); } catch { /* 保存できなくても表示はできる */ }
  function zoom(step) {
    zi = Math.max(0, Math.min(ZOOMS.length - 1, step === 0 ? 2 : zi + step));
    applyZoom();
  }
  function applyZoom() {
    body.style.setProperty("--md-scale", ZOOMS[zi]);
    $(".pv-zoom").textContent = `${Math.round(ZOOMS[zi] * 100)}%`;
    try { localStorage.setItem("hub.md.zoom", String(zi)); } catch { /* 同上 */ }
  }

  let doc = null;      // { text, mtime, folder, path }
  async function load(keepScroll = false) {
    const top = scroller.scrollTop;
    try {
      doc = await ctx.call("read_text", { key });
    } catch (e) {
      body.innerHTML = `<p class="md-error"></p>`;
      body.querySelector(".md-error").textContent = e.message;
      return;
    }
    body.innerHTML = marked.parse(doc.text);
    for (const a of body.querySelectorAll("a[href]")) a.title ||= a.getAttribute("href");
    ctx.setStatus(doc.path);
    ctx.setTitle(doc.path.split(/[\\/]/).pop());
    if (keepScroll) scroller.scrollTop = top;
  }

  // リンクは窓の中で移動させず、行き先ごとに開き方を変える
  body.addEventListener("click", async (e) => {
    const a = e.target.closest("a[href]");
    if (!a) return;
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

  el.querySelector('[data-a="out"]').addEventListener("click", () => zoom(-1));
  el.querySelector('[data-a="in"]').addEventListener("click", () => zoom(1));
  el.querySelector('[data-a="edit"]').addEventListener("click", () => doc && ctx.host.openPath(doc.path).catch((e) => ctx.toast(e.message, "error")));
  el.querySelector('[data-a="reveal"]').addEventListener("click", () => doc && ctx.host.revealPath(doc.path).catch((e) => ctx.toast(e.message, "error")));
  scroller.addEventListener("keydown", (e) => {
    if (e.ctrlKey && (e.key === "+" || e.key === ";" || e.key === "=")) { e.preventDefault(); zoom(1); }
    if (e.ctrlKey && e.key === "-") { e.preventDefault(); zoom(-1); }
    if (e.ctrlKey && e.key === "0") { e.preventDefault(); zoom(0); }
    if (e.key === "F5") { e.preventDefault(); load(true); }
  });
  scroller.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); zoom(e.deltaY < 0 ? 1 : -1); } }, { passive: false });

  // 外で書き換えられたら読み直す（Claude が書き直したときなど）
  setInterval(async () => {
    if (!doc || document.visibilityState !== "visible") return;
    const m = await ctx.call("mtime", { key }).catch(() => null);
    if (m && m !== doc.mtime) load(true);
  }, POLL_MS);

  applyZoom();
  await load();
  scroller.focus();
}
