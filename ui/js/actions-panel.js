// actions-panel.js — L1モジュール（既存コマンドを呼ぶだけ）の画面を manifest.actions から自動で作る。
// モジュール側は画面のコードを書かなくてよい。
import { api, selectBox } from "./hub.js";
import { icons, fileIcon } from "./icons.js";
import { t } from "./i18n.js";

export async function mount(el, ctx) {
  const action = (ctx.module.actions || [])[0];
  if (!action) {
    el.innerHTML = `<div class="empty"></div>`;
    el.firstChild.textContent = t("action.none");
    return;
  }
  const accepts = (action.accepts || []).map((s) => s.toLowerCase());
  const values = Object.fromEntries((action.params || []).map((p) => [p.name, p.default ?? ""]));
  let file = "";

  el.innerHTML = `
    <div class="form">
      <div class="drop" id="drop">
        <div class="drop-ico">${icons.upload}</div>
        <div id="drop-text"></div>
        <div class="drop-or" id="drop-or"></div>
        <button class="btn" id="pick" type="button"></button>
      </div>
      <div id="fields"></div>
      <div class="btn-row"><button class="btn primary" id="run" type="button" disabled></button></div>
      <div class="results" id="results"></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  $("#run").textContent = action.label || t("action.run");
  $("#pick").textContent = t("action.pick");
  $("#drop-or").textContent = t("action.or");

  // ---- ファイルの受け取り ----
  const acceptLabel = accepts.length ? accepts.join(" / ") : t("action.file");
  function showFile() {
    const drop = $("#drop");
    drop.classList.toggle("has-file", !!file);
    $("#drop-text").innerHTML = "";
    if (file) {
      const name = file.split(/[\\/]/).pop();
      const ext = name.split(".").pop().toLowerCase();
      const d = document.createElement("div");
      d.style.cssText = "display:flex;gap:8px;align-items:center";
      d.innerHTML = fileIcon(ext);
      const s = document.createElement("span");
      s.className = "file";
      s.textContent = name;
      s.title = file;
      d.append(s);
      $("#drop-text").append(d);
    } else {
      $("#drop-text").textContent = t("action.dropHere", { accept: acceptLabel });
    }
    $("#drop-or").hidden = !!file;
    $("#drop .drop-ico").hidden = !!file;
    $("#run").disabled = !file;
  }
  function setFile(path) {
    if (accepts.length && !accepts.some((a) => path.toLowerCase().endsWith(a))) {
      ctx.toast(t("action.wrongType", { accept: acceptLabel }), "error");
      return;
    }
    file = path;
    showFile();
    ctx.setStatus("");
  }
  showFile();

  const drop = $("#drop");
  el.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  el.addEventListener("dragleave", (e) => { if (!el.contains(e.relatedTarget)) drop.classList.remove("over"); });
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (!ctx.isNative()) ctx.toast(t("action.browserDrop"), "error", 4500);
  });
  ctx.onNativeDrop((paths) => paths[0] && setFile(paths[0]));

  $("#pick").addEventListener("click", async () => {
    if (!ctx.isNative()) {
      const p = window.prompt(t("action.promptPath"));
      if (p) setFile(p.trim().replace(/^"|"$/g, ""));
      return;
    }
    const picked = await ctx.host.pickFiles(ctx.id).catch(() => null);
    if (picked?.length) setFile(picked[0]);
  });

  // ---- パラメータ入力欄（manifest.params から作る） ----
  function renderFields() {
    const box = $("#fields");
    box.replaceChildren();
    for (const p of action.params || []) {
      if (p.showIf && Object.entries(p.showIf).some(([k, v]) => values[k] !== v)) continue;
      const label = document.createElement("label");
      label.className = "field";
      const span = document.createElement("span");
      span.textContent = p.label || p.name;
      let input;
      if (p.type === "select") {
        // 自前のプルダウン（開いた一覧もHubの配色で描く）。<label> の中だと押下が二重に届くので div にする
        const lid = `lbl-${p.name}`;
        span.id = lid;
        const field = document.createElement("div");
        field.className = "field";
        const sb = selectBox({
          options: (p.options || []).map((o) => (typeof o === "object" ? o : { value: o, label: o })),
          value: values[p.name],
          labelledBy: lid,
          onChange: (v) => {
            values[p.name] = v;
            if ((action.params || []).some((q) => q.showIf && p.name in q.showIf)) renderFields();
          },
        });
        field.append(span, sb);
        box.append(field);
        continue;
      } else {
        input = document.createElement("input");
        input.type = p.type === "number" ? "number" : "text";
        if (p.min !== undefined) input.min = p.min;
        if (p.max !== undefined) input.max = p.max;
        if (p.step !== undefined) input.step = p.step;
        if (p.placeholder) input.placeholder = p.placeholder;
      }
      input.value = values[p.name];
      input.addEventListener("change", () => {
        values[p.name] = p.type === "number" ? Number(input.value) : input.value;
        if ((action.params || []).some((q) => q.showIf && p.name in q.showIf)) renderFields();
      });
      label.append(span, input);
      box.append(label);
    }
    box.style.cssText = "display:grid;gap:10px";
  }
  renderFields();

  // ---- 実行と結果 ----
  $("#run").addEventListener("click", async () => {
    const btn = $("#run");
    btn.disabled = true;
    btn.textContent = t("action.running");
    ctx.setStatus("");
    const results = $("#results");
    results.replaceChildren();
    try {
      const r = await api("action", { module: ctx.module.id, action: action.id, file, params: values });
      if (!r.ok) {
        const pre = document.createElement("pre");
        pre.className = "log error";
        pre.textContent = (r.stderr || r.stdout || t("action.exitCode", { code: r.code })).trim();
        results.append(pre);
        ctx.setStatus(t("common.failed"));
        return;
      }
      const outs = r.result?.outputs || [];
      ctx.setStatus(t("action.wrote", { n: outs.length }));
      if (r.result?.folder) {
        const row = document.createElement("div");
        row.className = "btn-row";
        const b = document.createElement("button");
        b.className = "btn";
        b.textContent = t("action.openFolder");
        b.addEventListener("click", () => ctx.host.openPath(r.result.folder).catch((e) => ctx.toast(e.message, "error")));
        row.append(b);
        results.append(row);
      }
      for (const o of outs.slice(0, 50)) {
        const name = o.split(/[\\/]/).pop();
        const row = document.createElement("div");
        row.className = "out";
        row.innerHTML = fileIcon(name.split(".").pop().toLowerCase());
        const s = document.createElement("span");
        s.className = "name";
        s.textContent = name;
        const open = document.createElement("button");
        open.className = "icon-btn";
        open.title = t("action.open");
        open.setAttribute("aria-label", t("action.open"));
        open.innerHTML = icons.open;
        open.addEventListener("click", () => ctx.host.openPath(o).catch((e) => ctx.toast(e.message, "error")));
        row.append(s, open);
        results.append(row);
      }
    } catch (e) {
      ctx.toast(e.message, "error", 5000);
      ctx.setStatus(t("common.failed"));
    } finally {
      btn.disabled = !file;
      btn.textContent = action.label || t("action.run");
    }
  });
}
