// pdf/ui/panel.js — ビューアのパネル（モジュール id は前の版のまま "pdf"）。
//   ・バーの「ビューア」から開く窓（id = "pdf"）… 開く場所: ドロップ・ファイルを選ぶ・最近開いたもの・「プログラムから開く」の登録
//   ・1 つのファイルを見る窓（id = "pdf:<key>"）… PDF は viewer.js、画像は image.js、Markdown は markdown.js
import { icons } from "/ui/js/icons.js";

export const OPENS = /\.(pdf|png|jpe?g|jpe|jfif|gif|webp|bmp|tiff?|md|markdown)$/i;

export async function mount(el, ctx) {
  if (ctx.instance) {
    const info = await ctx.call("doc_info", { key: ctx.instance }).catch(() => null);
    const viewer = await import(info?.kind === "image" ? "./image.js" : info?.kind === "md" ? "./markdown.js" : "./viewer.js");
    return viewer.mount(el, ctx);
  }
  const t = ctx.t;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./pdf.css", import.meta.url).href;
  document.head.append(css);

  const root = document.createElement("div");
  root.className = "pdf-home";
  el.append(root);

  async function openPath(path) {
    try {
      const r = await ctx.call("open_doc", { path });
      const w = await ctx.host.openPanel(r.panel);
      if (!ctx.isNative() && w?.url) window.open(w.url, r.panel, "width=880,height=1000");
      await renderRecent();
    } catch (e) { ctx.toast(e.message, "error", 5000); }
  }

  // ---- 開く ----
  const drop = document.createElement("div");
  drop.className = "drop";
  drop.innerHTML = `<div class="drop-ico">${icons.viewer}</div><div class="drop-text"></div><div class="drop-or"></div><button class="btn" type="button"></button>`;
  drop.querySelector(".drop-text").textContent = t("pdf.dropToOpen");
  drop.querySelector(".drop-or").textContent = t("action.or");
  const pick = drop.querySelector("button");
  pick.textContent = t("action.pick");
  pick.addEventListener("click", async () => {
    if (!ctx.isNative()) {
      const p = window.prompt(t("action.promptPath"));
      if (p) openPath(p.trim().replace(/^"|"$/g, ""));
      return;
    }
    const picked = await ctx.host.pickFiles(ctx.id).catch(() => null);
    for (const p of picked || []) await openPath(p);
  });
  el.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  el.addEventListener("dragleave", (e) => { if (!el.contains(e.relatedTarget)) drop.classList.remove("over"); });
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (!ctx.isNative()) ctx.toast(t("action.browserDrop"), "error", 4500);
  });
  ctx.onNativeDrop(async (paths) => { for (const p of paths) if (OPENS.test(p)) await openPath(p); });
  root.append(drop);

  // ---- 最近開いた PDF ----
  const recentBox = document.createElement("section");
  recentBox.className = "pdf-recent";
  root.append(recentBox);

  async function renderRecent() {
    const list = await ctx.call("recent").catch(() => []);
    recentBox.replaceChildren();
    if (!list.length) return;
    const h = document.createElement("h2");
    h.className = "pdf-h";
    h.textContent = t("pdf.recent");
    recentBox.append(h);
    for (const d of list.slice(0, 8)) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = d.kind === "image" ? "pdf-row img" : "pdf-row";
      row.disabled = !d.exists;
      row.innerHTML = `${d.kind === "image" ? icons.image : d.kind === "md" ? icons.text : icons.pdf}<span class="pdf-row-text"><span class="pdf-row-name"></span><span class="pdf-row-folder"></span></span>`;
      row.querySelector(".pdf-row-name").textContent = d.name;
      row.querySelector(".pdf-row-folder").textContent = d.exists ? d.folder : t("pdf.missing");
      row.title = `${d.folder}\\${d.name}`;
      row.addEventListener("click", async () => {
        const w = await ctx.host.openPanel(`pdf:${d.key}`).catch((e) => ctx.toast(e.message, "error"));
        if (!ctx.isNative() && w?.url) window.open(w.url, `pdf:${d.key}`, "width=880,height=1000");
      });
      row.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        ctx.contextMenu([
          { label: t("folders.reveal"), icon: icons.reveal, disabled: !d.exists,
            onClick: async () => ctx.host.revealPath(await ctx.call("reveal_path", { key: d.key })).catch((er) => ctx.toast(er.message, "error")) },
          { label: t("pdf.forget"), icon: icons.close, onClick: async () => { await ctx.call("forget", { key: d.key }); renderRecent(); } },
        ], e.clientX, e.clientY);
      });
      recentBox.append(row);
    }
  }

  // ---- 「プログラムから開く」への登録 ----
  const assoc = document.createElement("section");
  assoc.className = "pdf-assoc";
  root.append(assoc);
  async function renderAssoc() {
    const a = await ctx.call("association").catch(() => ({ supported: false }));
    assoc.replaceChildren();
    if (!a.supported) return;
    const row = document.createElement("div");
    row.className = "set-switch";
    const l = document.createElement("span");
    l.textContent = t("pdf.assoc");
    const sw = document.createElement("button");
    sw.type = "button";
    sw.className = "switch";
    sw.setAttribute("role", "switch");
    sw.setAttribute("aria-checked", String(!!a.registered));
    sw.setAttribute("aria-label", t("pdf.assoc"));
    sw.innerHTML = `<span class="knob"></span>`;
    sw.addEventListener("click", async () => {
      try { await ctx.call("set_association", { on: !a.registered }); await renderAssoc(); }
      catch (e) { ctx.toast(e.message, "error", 6000); }
    });
    row.append(l, sw);
    const note = document.createElement("p");
    note.className = "set-note";
    note.textContent = a.registered ? t("pdf.assocOn") : t("pdf.assocOff");
    assoc.append(row, note);
  }

  await Promise.all([renderRecent(), renderAssoc()]);
}
