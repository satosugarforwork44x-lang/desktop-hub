// web/ui/panel.js — Web ショートカット。押すと、ショートカットごとに選んだ開き方（ミニ窓 / ブラウザ）で開く
import { selectBox } from "/ui/js/hub.js";
import { icons } from "/ui/js/icons.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  let items = [];
  let have = { chrome: false, edge: false, firefox: false };
  el.innerHTML = `<div class="web"><div class="web-form" hidden></div><div class="web-list"></div></div>`;
  const $ = (s) => el.querySelector(s);
  ctx.addTool(icons.plus, t("web.add"), () => form());

  const modeLabel = (m) => t(`web.mode.${m}`);
  const modes = () => ["mini", "default", ...["chrome", "edge", "firefox"].filter((b) => have[b])];
  const host = (url) => { try { return new URL(url).host.replace(/^www\./, ""); } catch { return url; } };

  async function open(it) {
    try {
      const r = await ctx.call("launch", { id: it.id });
      if (r.mini) {
        if (ctx.isNative()) await ctx.host.openWeb(it.id, r.url, r.name);
        else window.open(r.url, `web-${it.id}`, "width=480,height=760");
      }
    } catch (e) { ctx.toast(e.message, "error", 5000); }
  }

  // ---------- 一覧 ----------
  function render() {
    const list = $(".web-list");
    list.replaceChildren();
    if (!items.length) {
      const e = document.createElement("div");
      e.className = "empty";
      e.textContent = t("web.empty");
      list.append(e);
      return;
    }
    for (const [i, it] of items.entries()) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "web-item";
      row.innerHTML = `<span class="web-badge"></span><span class="web-text"><span class="web-name"></span><span class="web-host"></span></span><span class="web-mode"></span>`;
      const letter = [...(it.name || host(it.url))][0] || "?";
      row.querySelector(".web-badge").textContent = letter.toUpperCase();
      row.querySelector(".web-badge").style.setProperty("--h", String((i * 47) % 360));
      row.querySelector(".web-name").textContent = it.name;
      row.querySelector(".web-host").textContent = host(it.url);
      const m = row.querySelector(".web-mode");
      m.innerHTML = it.open === "mini" ? icons.window : icons.open;
      m.title = modeLabel(it.open);
      row.title = `${it.url}\n${modeLabel(it.open)}`;
      row.addEventListener("click", () => open(it));
      row.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        ctx.contextMenu([
          { label: t("web.edit"), icon: icons.edit, onClick: () => form(it) },
          { label: t("web.copy"), icon: icons.text, onClick: () => navigator.clipboard.writeText(it.url).then(() => ctx.toast(t("web.copied"))) },
          "-",
          { label: t("web.up"), icon: icons.up, disabled: i === 0, onClick: () => move(i, -1) },
          { label: t("web.down"), icon: icons.down, disabled: i === items.length - 1, onClick: () => move(i, 1) },
          "-",
          { label: t("web.delete"), icon: icons.trash, onClick: async () => { await ctx.call("remove", { id: it.id }); load(); } },
        ], e.clientX, e.clientY);
      });
      list.append(row);
    }
  }
  async function move(i, d) {
    const ids = items.map((x) => x.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    items = await ctx.call("reorder", { ids });
    render();
  }

  // ---------- 追加・書き換え ----------
  function form(it = null) {
    const f = $(".web-form");
    f.hidden = false;
    f.innerHTML = `
      <label class="field"><span id="wf-url"></span><input class="wf-url" type="url" inputmode="url" spellcheck="false"></label>
      <label class="field"><span id="wf-name"></span><input class="wf-name" maxlength="60"></label>
      <div class="field"><span id="wf-mode"></span><div class="wf-mode"></div></div>
      <p class="set-note wf-note"></p>
      <div class="btn-row"><button class="btn primary wf-save" type="button"></button><button class="btn wf-cancel" type="button"></button></div>`;
    f.querySelector("#wf-url").textContent = "URL";
    f.querySelector("#wf-name").textContent = t("web.name");
    f.querySelector("#wf-mode").textContent = t("web.openWith");
    f.querySelector(".wf-save").textContent = it ? t("web.update") : t("web.add");
    f.querySelector(".wf-cancel").textContent = t("cal.cancel");
    const url = f.querySelector(".wf-url"), name = f.querySelector(".wf-name");
    url.placeholder = "https://news.example.com";
    name.placeholder = t("web.nameHint");
    url.value = it?.url || "";
    name.value = it?.name || "";
    let mode = it?.open || "mini";
    const note = () => { f.querySelector(".wf-note").textContent = t(`web.note.${mode === "chrome" || mode === "edge" ? "app" : mode}`); };
    const box = selectBox({ options: modes().map((m) => ({ value: m, label: modeLabel(m) })), value: mode, labelledBy: "wf-mode",
      onChange: (v) => { mode = v; note(); } });
    f.querySelector(".wf-mode").append(box);
    note();
    const done = () => { f.hidden = true; f.replaceChildren(); };
    const submit = async () => {
      try {
        await ctx.call("save", { url: url.value, name: name.value, open: mode, id: it?.id || null });
        done();
        load();
      } catch (e) { ctx.toast(e.message, "error", 5000); url.focus(); }
    };
    f.querySelector(".wf-save").addEventListener("click", submit);
    f.querySelector(".wf-cancel").addEventListener("click", done);
    for (const i of [url, name]) i.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) submit(); if (e.key === "Escape") done(); });
    url.focus();
  }

  async function load() {
    try { items = await ctx.call("items"); } catch (e) { ctx.toast(e.message, "error"); }
    render();
  }
  have = await ctx.call("browsers").catch(() => have);
  await load();
}
