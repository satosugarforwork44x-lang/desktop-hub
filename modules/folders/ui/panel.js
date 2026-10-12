// folders/ui/panel.js — フォルダ窓（1レジストリ = 1窓）の中身
import { icons, fileIcon } from "/ui/js/icons.js";

export async function mount(el, ctx) {
  const reg = ctx.instance;
  const t = ctx.t;
  if (!reg) return chooser(el, ctx);

  const cache = new Map();          // rel → items（開いたフォルダの中身）
  const expanded = new Set([""]);   // 開いているフォルダ（"" は一番上）
  let selected = new Set();
  let dropRel = null;               // ドロップ先（null=なし, ""=一番上）
  let lastNativeTarget = "";        // エクスプローラーからのドロップ先を覚えておく
  let undoCount = 0;
  let rootPath = "";

  const tree = document.createElement("div");
  tree.className = "tree";
  tree.tabIndex = 0;
  tree.setAttribute("role", "tree");
  el.append(tree);

  // ---- 見出しのボタン ----
  const undoBtn = ctx.addTool(icons.undo, t("folders.undo"), doUndo);
  ctx.addTool(icons.newFolder, t("folders.newFolder"), () => newFolder(""));
  ctx.addTool(icons.refresh, t("folders.refresh"), () => reload());

  // ---- 読み込み ----
  async function load(rel) {
    const r = await ctx.call("list_dir", { registry: reg, rel });
    cache.set(rel, r.items);
    if (rel === "") { undoCount = r.undo; rootPath = r.path; }
    return r.items;
  }
  async function reload() {
    try {
      for (const rel of [...expanded]) {
        try { await load(rel); } catch { expanded.delete(rel); cache.delete(rel); } // 消えたフォルダは閉じる
      }
      render();
    } catch (e) {
      ctx.toast(e.message, "error", 5000);
    }
  }

  // ---- 描画 ----
  function render() {
    tree.replaceChildren();
    const top = cache.get("") || [];
    if (!top.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = t("folders.empty");
      tree.append(empty);
    }
    const walk = (items, depth) => {
      for (const it of items) {
        tree.append(row(it, depth));
        if (it.dir && expanded.has(it.rel) && cache.has(it.rel)) walk(cache.get(it.rel), depth + 1);
      }
    };
    walk(top, 0);
    undoBtn.disabled = undoCount === 0;
    undoBtn.title = undoCount ? t("folders.undoLeft", { n: undoCount }) : t("folders.undoNone");
    const n = top.length;
    ctx.setStatus(n ? t("folders.items", { n }) : "");
  }

  function row(it, depth) {
    const r = document.createElement("div");
    r.className = "row";
    r.dataset.rel = it.rel;
    r.dataset.dir = it.dir ? "1" : "";
    r.style.setProperty("--depth", depth);
    r.draggable = true;
    r.tabIndex = -1;
    r.setAttribute("role", "treeitem");
    if (it.dir) r.setAttribute("aria-expanded", String(expanded.has(it.rel)));
    if (selected.has(it.rel)) r.classList.add("selected");
    r.innerHTML = it.dir ? icons.chevron + icons.folderFill : `<span class="chev none"></span>${fileIcon(it.ext)}`;
    if (it.dir && expanded.has(it.rel)) r.querySelector(".chev").classList.add("open");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = it.name;
    r.append(name);
    r.title = it.dir ? it.name : `${it.name}\n${fmtSize(it.size)} · ${new Date(it.mtime * 1000).toLocaleString(document.documentElement.lang === "ja" ? "ja-JP" : "en-US")}`;
    return r;
  }

  const fmtSize = (b) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB`);
  const parentOf = (rel) => (rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "");
  const rowOf = (target) => target.closest?.(".row");
  const itemOf = (rel) => [...cache.values()].flat().find((i) => i.rel === rel);

  async function toggle(rel) {
    if (expanded.has(rel)) expanded.delete(rel);
    else {
      expanded.add(rel);
      try { await load(rel); } catch (e) { ctx.toast(e.message, "error"); expanded.delete(rel); }
    }
    render();
  }

  // ---- クリック・キーボード ----
  tree.addEventListener("click", (e) => {
    const r = rowOf(e.target);
    if (!r) { selected.clear(); render(); return; }
    const rel = r.dataset.rel;
    if (e.ctrlKey) selected.has(rel) ? selected.delete(rel) : selected.add(rel);
    else selected = new Set([rel]);
    if (r.dataset.dir && e.target.closest(".chev")) toggle(rel);
    else render();
    tree.focus();
  });
  tree.addEventListener("dblclick", (e) => {
    const r = rowOf(e.target);
    if (!r) return;
    if (r.dataset.dir) toggle(r.dataset.rel);
    else openItem(r.dataset.rel);
  });
  tree.addEventListener("keydown", (e) => {
    const sel = [...selected];
    if (!sel.length) return;
    if (e.key === "Enter") { const it = itemOf(sel[0]); it?.dir ? toggle(sel[0]) : openItem(sel[0]); }
    if (e.key === "F2") startRename(sel[0]);
    if (e.key === "Delete") doTrash(sel);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = [...tree.querySelectorAll(".row")];
      const i = rows.findIndex((x) => x.dataset.rel === sel[sel.length - 1]);
      const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (next) { selected = new Set([next.dataset.rel]); render(); }
    }
  });

  // ---- 右クリックメニュー ----
  tree.addEventListener("contextmenu", async (e) => {
    e.preventDefault();
    const r = rowOf(e.target);
    if (!r) {
      ctx.contextMenu([
        { label: t("folders.newFolder"), icon: icons.newFolder, onClick: () => newFolder("") },
        { label: t("folders.reveal"), icon: icons.reveal, onClick: () => ctx.host.revealPath(rootPath).catch(err) },
      ], e.clientX, e.clientY);
      return;
    }
    const rel = r.dataset.rel;
    if (!selected.has(rel)) { selected = new Set([rel]); render(); }
    const rels = [...selected];
    const others = (await ctx.call("instances").catch(() => [])).filter((x) => x.id !== reg);
    ctx.contextMenu([
      { label: t("folders.open"), icon: icons.open, onClick: () => openItem(rel) },
      { label: t("folders.reveal"), icon: icons.reveal, onClick: () => reveal(rel) },
      { label: t("folders.rename"), icon: icons.rename, onClick: () => startRename(rel), disabled: rels.length > 1 },
      { label: t("folders.newFolderIn"), icon: icons.newFolder, onClick: () => newFolder(r.dataset.dir ? rel : parentOf(rel)) },
      "-",
      ...(others.length ? [{ label: t("folders.moveTo"), heading: true },
        ...others.map((o) => ({ label: o.label, icon: icons.move, onClick: () => moveTo(rels, o.id) }))] : []),
      "-",
      { label: rels.length > 1 ? t("folders.trashN", { n: rels.length }) : t("folders.trash"), icon: icons.trash, danger: true, onClick: () => doTrash(rels) },
    ], e.clientX, e.clientY);
  });

  // ---- ドラッグ＆ドロップ ----
  // フォルダ行 → その中へ。ファイル行 → そのファイルと同じ場所へ（旧版の「ファイル行に落とすと一番上に戻る」不具合を解消）
  const targetRel = (e) => {
    const r = rowOf(e.target);
    if (!r) return "";
    return r.dataset.dir ? r.dataset.rel : parentOf(r.dataset.rel);
  };
  function markDrop(rel) {
    if (rel === dropRel) return;
    dropRel = rel;
    tree.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target"));
    document.body.classList.toggle("drop-root", rel === "");
    if (rel) tree.querySelector(`.row[data-rel="${CSS.escape(rel)}"]`)?.classList.add("drop-target");
  }
  function clearDrop() {
    dropRel = null;
    tree.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target"));
    document.body.classList.remove("drop-root");
  }

  tree.addEventListener("dragstart", (e) => {
    const r = rowOf(e.target);
    if (!r) return;
    if (!selected.has(r.dataset.rel)) { selected = new Set([r.dataset.rel]); }
    e.dataTransfer.setData("application/x-hub-rels", JSON.stringify([...selected]));
    e.dataTransfer.effectAllowed = "move";
  });
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    markDrop(targetRel(e));
  });
  el.addEventListener("dragleave", (e) => { if (!el.contains(e.relatedTarget)) clearDrop(); });
  el.addEventListener("drop", async (e) => {
    e.preventDefault();
    const dest = targetRel(e);
    clearDrop();
    const internal = e.dataTransfer.getData("application/x-hub-rels");
    if (internal) {
      const rels = JSON.parse(internal).filter((r) => r !== dest && !dest.startsWith(r + "/"));
      if (rels.length) await run(() => ctx.call("move_within", { registry: reg, rels, dest_rel: dest }), t("folders.moved"));
      return;
    }
    // 外からのドロップ: フルパスは直後に ctx.onNativeDrop で届くので、落とした場所を覚えておく
    lastNativeTarget = dest;
    if (!ctx.isNative()) ctx.toast(t("folders.browserDrop"), "error", 4500);
  });
  ctx.onNativeDrop((paths) => {
    run(() => ctx.call("move_in", { registry: reg, paths, dest_rel: lastNativeTarget }), t("folders.imported"));
  });

  // ---- 操作 ----
  const err = (e) => ctx.toast(e.message, "error", 5000);
  async function run(fn, okMsg) {
    try {
      const r = await fn();
      const n = (r.moved || r.restored || r.trashed || []).length;
      if (r.errors?.length) ctx.toast(r.errors.join("\n"), "error", 6000);
      else if (okMsg && n) ctx.toast(t("folders.count", { msg: okMsg, n }));
      await reload();
      return r;
    } catch (e) { err(e); }
  }
  async function openItem(rel) {
    try { await ctx.host.openPath(await ctx.call("full_path", { registry: reg, rel })); } catch (e) { err(e); }
  }
  async function reveal(rel) {
    try { await ctx.host.revealPath(await ctx.call("full_path", { registry: reg, rel })); } catch (e) { err(e); }
  }
  function doUndo() { run(() => ctx.call("undo", { registry: reg }), t("folders.restored")); }
  function moveTo(rels, target) { run(() => ctx.call("move_to", { registry: reg, rels, target }), t("folders.movedTo", { target })); }
  function doTrash(rels) { run(() => ctx.call("trash", { registry: reg, rels }), t("folders.trashed")); selected.clear(); }
  async function newFolder(rel) {
    const r = await run(() => ctx.call("make_folder", { registry: reg, rel }));
    if (r?.rel) {
      if (rel) { expanded.add(rel); await reload(); }
      startRename(r.rel);
    }
  }

  // 名前の変更: 行の中で直接入力する（Enterで確定、Escで取り消し）
  function startRename(rel) {
    const r = tree.querySelector(`.row[data-rel="${CSS.escape(rel)}"]`);
    if (!r) return;
    const nameEl = r.querySelector(".name");
    const input = document.createElement("input");
    input.className = "rename";
    input.value = nameEl.textContent;
    nameEl.replaceWith(input);
    r.draggable = false;
    input.focus();
    const dot = input.value.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 && !r.dataset.dir ? dot : input.value.length); // 拡張子は選択しない
    let done = false;
    const finish = async (ok) => {
      if (done) return;
      done = true;
      const v = input.value.trim();
      if (ok && v && v !== nameEl.textContent) {
        const res = await run(() => ctx.call("rename", { registry: reg, rel, new_name: v }));
        if (res?.rel) selected = new Set([res.rel]);
      }
      render();
    };
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
  }

  // ---- 自動更新（外でファイルが増減しても追従する） ----
  window.addEventListener("focus", reload);
  setInterval(() => { if (document.visibilityState === "visible" && !tree.querySelector("input")) reload(); }, 10000);

  await reload();
}

// ---- 「フォルダ」タイルから開く一覧: 開く・バーに出す/しまう・新しく作る ----
async function chooser(el, ctx) {
  const t = ctx.t;
  el.innerHTML = `<div class="fchooser"><div class="fc-new"><input class="fc-input" maxlength="80"><button class="btn" type="button"></button></div><div class="fc-list"></div><p class="set-note fc-note"></p></div>`;
  const input = el.querySelector(".fc-input");
  const add = el.querySelector(".fc-new .btn");
  input.placeholder = t("bar.folderPlaceholder");
  add.textContent = t("folders.create");
  el.querySelector(".fc-note").textContent = t("folders.chooserNote");

  async function create() {
    const name = input.value.trim();
    if (!name) return input.focus();
    try {
      await ctx.call("create_registry", { name });
      input.value = "";
      await render();
      await ctx.host.openPanel(`folders:${name}`);
    } catch (e) { ctx.toast(e.message, "error"); }
  }
  add.addEventListener("click", create);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) create(); });

  async function render() {
    const [list, s] = await Promise.all([ctx.call("instances"), ctx.host.settings()]);
    const hidden = new Set(s.barTiles?.hidden || []);
    const box = el.querySelector(".fc-list");
    box.replaceChildren();
    if (!list.length) {
      const e = document.createElement("div");
      e.className = "empty";
      e.textContent = t("folders.none");
      box.append(e);
    }
    for (const it of list) {
      const pid = `folders:${it.id}`;
      const row = document.createElement("div");
      row.className = "fc-row";
      row.innerHTML = `<button type="button" class="fc-open">${icons.folder}<span class="fc-name"></span></button><button type="button" class="icon-btn fc-pin"></button>`;
      row.querySelector(".fc-name").textContent = it.label;
      row.querySelector(".fc-open").addEventListener("click", () => ctx.host.openPanel(pid).catch((e) => ctx.toast(e.message, "error")));
      const pin = row.querySelector(".fc-pin");
      const onBar = !hidden.has(pid);
      pin.innerHTML = onBar ? icons.pin : icons.eyeOff;
      pin.setAttribute("aria-pressed", String(onBar));
      pin.title = t(onBar ? "folders.offBar" : "folders.onBar");
      pin.setAttribute("aria-label", `${it.label}: ${pin.title}`);
      pin.addEventListener("click", async () => {
        const next = new Set(hidden);
        onBar ? next.add(pid) : next.delete(pid);
        try {
          await ctx.host.saveSettings({ "bar.tiles": { order: s.barTiles?.order || [], hidden: [...next] } });
          render();
        } catch (e) { ctx.toast(e.message, "error"); }
      });
      box.append(row);
    }
  }
  await render();
}
