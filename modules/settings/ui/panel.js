// settings/ui/panel.js — 設定画面。変えた項目だけを保存し、反映できるものはその場で反映する
import { icons } from "/ui/js/icons.js";
import { listTiles, arrange } from "/ui/js/tiles.js";
import { ACCENTS } from "/ui/js/theme.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  let s = await ctx.host.settings();
  let tileList = (await listTiles().catch(() => ({ tiles: [] }))).tiles;

  const root = document.createElement("div");
  root.className = "settings";
  el.append(root);

  // 選択肢が少ない項目は、プルダウンより一目で分かる「区切りボタン」にする
  function segmented(key, options, current) {
    const g = document.createElement("div");
    g.className = "seg";
    g.setAttribute("role", "radiogroup");
    for (const [value, label, icon] of options) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(value === current));
      b.innerHTML = `${icon || ""}<span></span>`;
      b.querySelector("span").textContent = label;
      if (key) b.addEventListener("click", () => save({ [key]: value }));
      g.append(b);
    }
    return g;
  }

  function section(title, ...children) {
    const sec = document.createElement("section");
    sec.className = "set-sec";
    const h = document.createElement("h2");
    h.textContent = title;
    sec.append(h, ...children);
    return sec;
  }

  function row(label, control, note) {
    const r = document.createElement("div");
    r.className = "set-row";
    const l = document.createElement("div");
    l.className = "set-label";
    l.textContent = label;
    r.append(l, control);
    if (note) {
      const n = document.createElement("p");
      n.className = "set-note";
      n.textContent = note;
      r.append(n);
    }
    return r;
  }

  function switchRow(label, key, on) {
    const wrap = document.createElement("div");
    wrap.className = "set-switch";
    const l = document.createElement("span");
    l.textContent = label;
    const sw = document.createElement("button");
    sw.type = "button";
    sw.className = "switch";
    sw.setAttribute("role", "switch");
    sw.setAttribute("aria-checked", String(on));
    sw.setAttribute("aria-label", label);
    sw.innerHTML = `<span class="knob"></span>`;
    if (key) sw.addEventListener("click", () => save({ [key]: !on }));
    wrap.append(l, sw);
    return wrap;
  }

  function note(text) {
    const n = document.createElement("p");
    n.className = "set-note";
    n.textContent = text;
    return n;
  }

  // ---- バーのタイル: ドラッグ（または ↑↓ キー）で並べ替え、目のボタンで表示／非表示 ----
  function tilesEditor() {
    const list = document.createElement("div");
    list.className = "set-tiles";
    list.setAttribute("role", "list");
    const items = arrange(tileList, s.barTiles);
    const saveTiles = () => {
      const rows = [...list.querySelectorAll(".set-tile")];
      save({ "bar.tiles": { order: rows.map((r) => r.dataset.pid), hidden: rows.filter((r) => r.classList.contains("off")).map((r) => r.dataset.pid) } });
    };
    for (const it of items) {
      const r = document.createElement("div");
      r.className = "set-tile";
      r.setAttribute("role", "listitem");
      r.dataset.pid = it.pid;
      r.classList.toggle("off", it.hidden);
      r.innerHTML = `<button type="button" class="set-grip"></button><span class="set-tile-ico">${it.icon}</span><span class="set-tile-name"></span><button type="button" class="icon-btn set-eye"></button>`;
      r.querySelector(".set-tile-name").textContent = it.label;
      const grip = r.querySelector(".set-grip");
      grip.innerHTML = icons.grip;
      grip.title = t("set.tileDrag");
      grip.setAttribute("aria-label", `${it.label}: ${t("set.tileDrag")}`);
      const eye = r.querySelector(".set-eye");
      eye.innerHTML = it.hidden ? icons.eyeOff : icons.eye;
      eye.title = t(it.hidden ? "set.tileShow" : "set.tileHide");
      eye.setAttribute("aria-label", `${it.label}: ${eye.title}`);
      eye.setAttribute("aria-pressed", String(!it.hidden));
      eye.addEventListener("click", () => { r.classList.toggle("off"); saveTiles(); });
      // キーボード: ↑↓ で動かす
      grip.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        e.preventDefault();
        const sib = e.key === "ArrowUp" ? r.previousElementSibling : r.nextElementSibling;
        if (!sib) return;
        e.key === "ArrowUp" ? sib.before(r) : sib.after(r);
        saveTiles();
      });
      // マウス: つまみを掴んで上下に動かす
      grip.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        r.classList.add("dragging");
        const before = [...list.children].indexOf(r);
        const move = (ev) => {
          const over = document.elementFromPoint(list.getBoundingClientRect().left + 20, ev.clientY)?.closest(".set-tile");
          if (!over || over === r || over.parentElement !== list) return;
          const box = over.getBoundingClientRect();
          ev.clientY < box.top + box.height / 2 ? over.before(r) : over.after(r);
        };
        const up = () => {
          r.classList.remove("dragging");
          document.removeEventListener("pointermove", move);
          document.removeEventListener("pointerup", up);
          if ([...list.children].indexOf(r) !== before) saveTiles();
        };
        document.addEventListener("pointermove", move);   // 窓の中ならどこまで動かしても追いかける
        document.addEventListener("pointerup", up);
      });
      list.append(r);
    }
    if (!items.length) list.append(note(t("set.tilesEmpty")));
    return list;
  }

  async function save(changes) {
    try {
      const r = await ctx.host.saveSettings(changes);
      s = r.settings;
      render();
      if (r.restart) showRestart();
      else ctx.toast(t("set.saved"));
    } catch (e) { ctx.toast(e.message, "error", 5000); }
  }

  function showRestart() {
    root.querySelector(".set-restart")?.remove();
    const box = document.createElement("div");
    box.className = "set-restart";
    const p = document.createElement("span");
    p.textContent = t("set.needRestart");
    const b = document.createElement("button");
    b.className = "btn primary";
    b.type = "button";
    b.textContent = t("set.restart");
    b.addEventListener("click", async () => {
      try { await ctx.host.restart(); } catch (e) { ctx.toast(e.message, "error", 5000); }
    });
    box.append(p, b);
    root.prepend(box);
  }

  function mcpSnippet() {
    const sep = s.appRoot.includes("\\") ? "\\" : "/";
    return JSON.stringify({ mcpServers: { hub: { command: s.python, args: [`${s.appRoot}${sep}hub_mcp.py`] } } }, null, 2);
  }

  function render() {
    const restart = root.querySelector(".set-restart");
    root.replaceChildren();
    if (restart) root.append(restart);

    // 見た目: 明るさ（区切りボタン）と色（グラデーションの見本を並べる）
    const swatches = document.createElement("div");
    swatches.className = "swatches";
    swatches.setAttribute("role", "radiogroup");
    swatches.setAttribute("aria-label", t("set.accent"));
    for (const a of ACCENTS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `swatch sw-${a}`;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(s.accent === a));
      b.innerHTML = `<span class="swatch-chip"></span><span class="swatch-name"></span>`;
      b.querySelector(".swatch-name").textContent = t(`set.accent.${a}`);
      b.addEventListener("click", () => save({ "appearance.accent": a }));
      swatches.append(b);
    }
    root.append(section(t("set.look"),
      row(t("set.mode"), segmented("appearance.mode", [["auto", t("set.auto")], ["dark", t("set.dark")], ["light", t("set.light")]], s.mode),
        t("set.modeNote")),
      row(t("set.accent"), swatches),
    ));

    root.append(section(t("set.display"),
      row(t("set.lang"), segmented("lang", [["auto", t("set.auto")], ["ja", "日本語"], ["en", "English"]], s.lang)),
      row(t("set.dock"), segmented("bar.dock", [
        ["top", t("set.top"), icons.dockTop], ["bottom", t("set.bottom"), icons.dockBottom],
        ["left", t("set.left"), icons.dockLeft], ["right", t("set.right"), icons.dockRight]], s.dock), t("set.dockNote")),
      row(t("set.labels"), segmented("bar.labels", [["auto", t("set.auto")], ["icons", t("set.iconsOnly")], ["folders", t("set.foldersOnly")], ["full", t("set.full")]], s.labels),
        t("set.labelsNote")),
      row(t("set.corners"), segmented("windows.corners", [["round", t("set.round")], ["small", t("set.small")], ["square", t("set.square")]], s.corners)),
      switchRow(t("set.intro"), "bar.intro", s.intro),
    ));

    root.append(section(t("set.tiles"),
      row(t("set.folderMode"), segmented("bar.folders", [["auto", t("set.fmAuto")], ["each", t("set.fmEach")], ["group", t("set.fmGroup")]], s.barFolders || "auto"),
        t("set.folderModeNote")),
      tilesEditor(), note(t("set.tilesNote"))));

    // Windows の起動時に開く（設定ファイルではなく、スタートアップのショートカットの有無で決まる）
    if (s.windows) {
      // Windows の起動時に開く・スタートメニュー・デスクトップ（設定ファイルではなく、ショートカットの有無で決まる）
      const sc = (label, where) => {
        const r = switchRow(label, null, !!s.shortcuts?.[where]);
        r.querySelector(".switch").addEventListener("click", async () => {
          try {
            await ctx.host.setShortcut(where, !s.shortcuts?.[where]);
            s = await ctx.host.settings();
            render();
            ctx.toast(t("set.saved"));
          } catch (e) { ctx.toast(e.message, "error", 6000); }
        });
        return r;
      };
      root.append(section(t("set.startup"),
        sc(t("set.autostart"), "startup"),
        sc(t("set.startMenu"), "startmenu"),
        sc(t("set.desktopIcon"), "desktop"),
        note(t("set.shortcutNote"))));
    }

    // フォルダの場所
    const pathBox = document.createElement("div");
    pathBox.className = "set-path";
    const code = document.createElement("code");
    code.textContent = s.foldersRootResolved;
    code.title = s.foldersRootResolved;
    const change = document.createElement("button");
    change.className = "btn";
    change.type = "button";
    change.textContent = t("set.change");
    change.addEventListener("click", async () => {
      if (!ctx.isNative()) {
        const v = window.prompt(t("set.folderPrompt"), s.foldersRoot);
        if (v) save({ "modules.folders.root": v.trim() });
        return;
      }
      const picked = await ctx.host.pickFolder(ctx.id).catch(() => null);
      if (picked) save({ "modules.folders.root": picked.replaceAll("\\", "/") });
    });
    const open = document.createElement("button");
    open.className = "icon-btn";
    open.type = "button";
    open.title = t("set.openFolder");
    open.setAttribute("aria-label", t("set.openFolder"));
    open.innerHTML = icons.open;
    open.addEventListener("click", () => ctx.host.openPath(s.foldersRootResolved).catch((e) => ctx.toast(e.message, "error")));
    pathBox.append(code, open, change);
    root.append(section(t("set.folders"), row(t("set.folderRoot"), pathBox, t("set.folderNote"))));

    // Claude（MCP）: 予定・Web ショートカットを見せるか ＋ フォルダ窓ごとに「見せない / 読む / 読み書き」
    const mcpSwitch = (label, key, on) => {
      const sw = document.createElement("button");
      sw.type = "button";
      sw.className = "switch";
      sw.setAttribute("role", "switch");
      sw.setAttribute("aria-checked", String(on));
      sw.setAttribute("aria-label", label);
      sw.innerHTML = `<span class="knob"></span>`;
      sw.addEventListener("click", () => save({ [key]: !on }));
      const r = document.createElement("div");
      r.className = "set-switch";
      const l = document.createElement("span");
      l.textContent = label;
      r.append(l, sw);
      return r;
    };
    const swRow = mcpSwitch(t("set.mcpCalendar"), "mcp.calendar", s.mcpCalendar);
    const webRow = mcpSwitch(t("set.mcpWeb"), "mcp.web", s.mcpWeb);
    const imgRow = mcpSwitch(t("set.mcpImages"), "mcp.images", s.mcpImages);

    const list = document.createElement("div");
    list.className = "set-panels";
    for (const name of s.panels) {
      const cur = s.mcpPanels[name] || "hidden";
      const r = document.createElement("div");
      r.className = "set-panel";
      const n = document.createElement("span");
      n.className = "set-panel-name";
      n.innerHTML = icons.folder;
      const nm = document.createElement("span");
      nm.textContent = name;
      n.append(nm);
      const seg = segmented(null, [["hidden", t("set.hidden")], ["read", t("set.read")], ["write", t("set.write")]], cur);
      seg.classList.add("seg-sm");
      seg.querySelectorAll("button").forEach((b, i) => {
        const v = ["hidden", "read", "write"][i];
        b.onclick = () => save({ "mcp.panels": { ...s.mcpPanels, [name]: v } });
      });
      r.append(n, seg);
      list.append(r);
    }
    if (!s.panels.length) {
      const e = document.createElement("p");
      e.className = "set-note";
      e.textContent = t("set.noPanels");
      list.append(e);
    }

    const pre = document.createElement("pre");
    pre.className = "set-code";
    pre.textContent = mcpSnippet();
    const copy = document.createElement("button");
    copy.className = "btn";
    copy.type = "button";
    copy.textContent = t("set.copy");
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(mcpSnippet()); ctx.toast(t("set.copied")); }
      catch { ctx.toast(t("set.copyFailed"), "error"); }
    });
    root.append(section(t("set.claude"),
      swRow,
      webRow,
      imgRow,
      note(t("set.mcpImagesNote")),
      row(t("set.mcpPanels"), list, t("set.mcpPanelsNote")),
      row(t("set.mcpConfig"), pre, t("set.mcpConfigNote")),
      copy,
    ));

    // このHubについて
    const cfg = document.createElement("code");
    cfg.textContent = s.configPath;
    cfg.title = s.configPath;
    const ver = document.createElement("code");
    ver.textContent = `Hub ${s.version}`;
    const home = document.createElement("div");
    home.className = "set-path";
    const hc = document.createElement("code");
    hc.textContent = s.userHome;
    hc.title = s.userHome;
    const ho = document.createElement("button");
    ho.className = "icon-btn";
    ho.type = "button";
    ho.title = t("set.openFolder");
    ho.setAttribute("aria-label", t("set.openFolder"));
    ho.innerHTML = icons.open;
    ho.addEventListener("click", () => ctx.host.openPath(s.userHome).catch((e) => ctx.toast(e.message, "error")));
    home.append(hc, ho);
    root.append(section(t("set.about"),
      row(t("set.version"), ver),
      row(t("set.userHome"), home, t("set.userHomeNote")),
      row(t("set.configFile"), cfg)));
  }

  render();
}
