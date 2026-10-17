// pdf/ui/office.js — Word / Excel / PowerPoint を見る窓（読むだけ。直すときは関連付けたアプリで開く）。
//   ・docx: 画面で表示する（docx-preview、Apache-2.0 ＋ JSZip、MIT。vendor に同梱）。ページの形・表・画像まで
//   ・xlsx / pptx: LibreOffice が入っていれば PDF にして、いつもの PDF ビューアで（見た目どおり・検索・印刷・文字のコピー）
//                  入っていなければ文字だけ（シートは表、スライドは 1 枚ずつ）を出し、LibreOffice の入れ方を案内する
//   ・docx も「PDF で見る」で LibreOffice の表示に切り替えられる（印刷向け）
import { TOKEN } from "/ui/js/hub.js";
import { icons } from "/ui/js/icons.js";

const ZOOMS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 2];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function loadScript(src) {
  return new Promise((ok, ng) => {
    if (document.querySelector(`script[data-src="${src}"]`)) return ok();
    const s = document.createElement("script");
    s.src = new URL(src, import.meta.url).href;
    s.dataset.src = src;
    s.onload = ok;
    s.onerror = () => ng(new Error(`${src} を読み込めない`));
    document.head.append(s);
  });
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
  const info = await ctx.call("doc_info", { key });
  const ext = info.name.split(".").pop().toLowerCase();
  const lo = await ctx.call("office_info").catch(() => ({ libreoffice: false }));
  ctx.setTitle(info.name);
  ctx.setStatus(`${info.folder}\\${info.name}`);

  // LibreOffice で PDF にして、PDF ビューアをこの窓の中で動かす
  async function asPdf() {
    el.innerHTML = `<div class="of-wait"><span class="of-spin"></span><span>${esc(t("office.converting"))}</span></div>`;
    try {
      const r = await ctx.call("office_to_pdf", { key });
      el.replaceChildren();
      const viewer = await import("./viewer.js");
      await viewer.mount(el, { ...ctx, instance: r.key, setTitle: () => ctx.setTitle(info.name) });
      ctx.addTool?.(icons.open, t("md.openWith"), () => ctx.host.openPath(`${info.folder}\\${info.name}`).catch((e) => ctx.toast(e.message, "error")));
    } catch (e) {
      ctx.toast(e.message, "error", 7000);
      if (ext === "docx") showDocx();
      else showText();
    }
  }

  // 上の帯（拡大縮小・PDF で見る・関連付けたアプリ・フォルダを表示）
  function bar(extra = "") {
    return `<div class="pv-bar">
      <button class="icon-btn" data-a="out" title="${esc(t("pdf.zoomOut"))}">${icons.zoomOut}</button>
      <span class="pv-zoom"></span>
      <button class="icon-btn" data-a="in" title="${esc(t("pdf.zoomIn"))}">${icons.zoomIn}</button>
      <span class="pv-grow"></span>${extra}
      ${lo.libreoffice ? `<button class="btn" data-a="pdf">${esc(t("office.asPdf"))}</button>` : ""}
      <button class="icon-btn" data-a="open" title="${esc(t("md.openWith"))}">${icons.open}</button>
      <button class="icon-btn" data-a="reveal" title="${esc(t("folders.reveal"))}">${icons.reveal}</button>
    </div>`;
  }
  function wire(root, target) {
    let zi = ZOOMS.indexOf(1);
    const apply = () => { target.style.zoom = ZOOMS[zi]; root.querySelector(".pv-zoom").textContent = `${Math.round(ZOOMS[zi] * 100)}%`; };
    root.querySelector('[data-a="out"]').addEventListener("click", () => { zi = Math.max(0, zi - 1); apply(); });
    root.querySelector('[data-a="in"]').addEventListener("click", () => { zi = Math.min(ZOOMS.length - 1, zi + 1); apply(); });
    root.querySelector('[data-a="pdf"]')?.addEventListener("click", asPdf);
    root.querySelector('[data-a="open"]').addEventListener("click", () => ctx.host.openPath(`${info.folder}\\${info.name}`).catch((e) => ctx.toast(e.message, "error")));
    root.querySelector('[data-a="reveal"]').addEventListener("click", () => ctx.host.revealPath(`${info.folder}\\${info.name}`).catch((e) => ctx.toast(e.message, "error")));
    root.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); zi = Math.max(0, Math.min(ZOOMS.length - 1, zi + (e.deltaY < 0 ? 1 : -1))); apply(); } }, { passive: false });
    apply();
  }

  // docx: docx-preview で表示（ページの形のまま）
  async function showDocx() {
    el.innerHTML = `<div class="pv of">${bar()}<div class="of-scroll"><div class="of-docx"></div></div></div>`;
    const box = el.querySelector(".of-docx");
    wire(el, box);
    try {
      await loadScript("./vendor/jszip/jszip.min.js");
      await loadScript("./vendor/docx-preview/docx-preview.min.js");
      const res = await fetch(`/blob/pdf/${key}?t=${encodeURIComponent(TOKEN)}&v=${info.mtime || 0}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await window.docx.renderAsync(await res.arrayBuffer(), box, null,
        { className: "docx", inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true, useBase64URL: true });
    } catch (e) {
      ctx.toast(`${t("office.failed")}: ${e.message}`, "error", 7000);
      showText();
    }
  }

  // 文字だけ（LibreOffice が無いとき）。xlsx はシートごとの表、pptx はスライドごとのカード
  async function showText() {
    const note = lo.libreoffice ? "" : `<div class="of-note">${icons.text}<span>${esc(t("office.needLo"))}</span></div>`;
    el.innerHTML = `<div class="pv of">${bar()}${note}<div class="of-scroll"><article class="of-text md-body"></article></div></div>`;
    const box = el.querySelector(".of-text");
    wire(el, box);
    let text;
    try { text = (await ctx.call("office_text", { key })).text; } catch (e) { box.textContent = e.message; return; }
    const blocks = text.split(/\n\n(?=--- )/);
    if (ext === "xlsx") {
      box.innerHTML = blocks.map((b) => {
        const [head, ...rows] = b.split("\n");
        const name = head.replace(/^--- シート: (.*) ---$/, "$1");
        return `<h3>${esc(name)}</h3><div class="of-table"><table>${rows.map((r) => `<tr>${r.split("\t").map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table></div>`;
      }).join("");
    } else if (ext === "pptx") {
      box.innerHTML = blocks.map((b) => {
        const [head, ...lines] = b.split("\n");
        const i = lines.findIndex((l) => l.startsWith("（ノート）"));
        const body = i < 0 ? lines : lines.slice(0, i), notes = i < 0 ? [] : lines.slice(i);
        return `<section class="of-slide"><div class="of-slide-no">${esc(head.replace(/^--- (.*) ---$/, "$1"))}</div>`
          + `<div class="of-slide-body">${body.map((l, j) => (j ? `<p>${esc(l)}</p>` : `<h3>${esc(l)}</h3>`)).join("")}</div>`
          + (notes.length ? `<div class="of-slide-notes">${esc(notes.join("\n").replace(/^（ノート）/, ""))}</div>` : "") + `</section>`;
      }).join("");
    } else {
      box.innerHTML = `<div class="md-plain">${esc(text)}</div>`;
    }
  }

  if (ext === "docx") await showDocx();
  else if (lo.libreoffice) await asPdf();
  else await showText();
}
