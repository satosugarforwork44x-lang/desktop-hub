// hub.js — 画面からPython（host）を呼ぶための共通の入口。全画面がこれを使う。
const params = new URLSearchParams(location.search);
export const TOKEN = params.get("t") || "";
export const PARAMS = params;

export class HubError extends Error {}

// /api/<path> を呼ぶ。失敗時は理由付きの HubError を投げる
export async function api(path, body = {}) {
  const res = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Token": TOKEN },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  if (!json.ok) throw new HubError(json.error || `HTTP ${res.status}`);
  return json.data;
}

// モジュールの公開関数を呼ぶ（manifest.exports に載っているものだけ）
export const call = (module, fn, args = {}) => api("call", { module, fn, args });

// 窓の操作・OS操作
export const host = {
  config: () => api("host/config"),
  openPanel: (id) => api("host/open_panel", { id }),
  closePanel: (id) => api("host/close_panel", { id }),
  togglePanel: (id) => api("host/toggle_panel", { id }),
  collapsePanel: (id, collapsed) => api("host/collapse_panel", { id, collapsed }),
  resizePanel: (id, w, h) => api("host/resize_panel", { id, w, h }),
  panelState: (id) => api("host/panel_state", { id }),
  openPanels: () => api("host/open_panels"),
  bar: (opts) => api("host/bar", opts),
  openPath: (path) => api("host/open_path", { path }),
  revealPath: (path) => api("host/reveal_path", { path }),
  pickFiles: (id) => api("host/pick_files", { id }),
  openWeb: (id, url, title) => api("host/open_web", { id, url, title }),
  quit: () => api("host/quit"),
  settings: () => api("host/settings"),
  saveSettings: (changes) => api("host/settings_set", { changes }),
  pickFolder: (id) => api("host/pick_folder", { id }),
  restart: () => api("host/restart"),
  setAutostart: (on) => api("host/autostart", { on }),
};

// 本物の窓（pywebview）の中か、ブラウザでの確認表示か
export const isNative = () => typeof window.pywebview !== "undefined";

// エクスプローラーからのドロップ。フルパスはPython側から window.hub._nativeDrop(paths) で届く
let dropHandler = null;
export function onNativeDrop(fn) { dropHandler = fn; }
window.hub = {
  _nativeDrop(paths) {
    if (dropHandler) dropHandler(paths);
  },
};

// 画面下のお知らせ（数秒で消える）
let toastTimer = null;
export function toast(message, kind = "info", ms = 3200) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.append(el);
  }
  el.textContent = message;
  el.classList.toggle("error", kind === "error");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), ms);
}

// 右クリックメニュー。items: [{label, icon, onClick, danger, submenu:[...]}, "-", {label:"見出し", heading:true}]
export function contextMenu(items, x, y) {
  closeMenus();
  const menu = document.createElement("div");
  menu.className = "menu";
  menu.setAttribute("role", "menu");
  for (const it of items) {
    if (it === "-") { menu.append(document.createElement("hr")); continue; }
    if (it.heading) {
      const h = document.createElement("div");
      h.className = "label";
      h.textContent = it.label;
      menu.append(h);
      continue;
    }
    const b = document.createElement("button");
    b.setAttribute("role", "menuitem");
    b.innerHTML = `${it.icon || ""}<span></span>`;
    b.querySelector("span").textContent = it.label;
    if (it.danger) b.classList.add("danger");
    if (it.disabled) b.disabled = true;
    b.addEventListener("click", () => { closeMenus(); it.onClick?.(); });
    menu.append(b);
  }
  document.body.append(menu);
  // 窓からはみ出さない位置に置く
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(x, innerWidth - r.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(y, innerHeight - r.height - 4))}px`;
  menu.querySelector("button")?.focus();
  setTimeout(() => document.addEventListener("pointerdown", outside, { once: true }), 0);
  function outside(e) { if (!menu.contains(e.target)) closeMenus(); else document.addEventListener("pointerdown", outside, { once: true }); }
  menu.addEventListener("keydown", (e) => {
    const btns = [...menu.querySelectorAll("button:not(:disabled)")];
    const i = btns.indexOf(document.activeElement);
    if (e.key === "Escape") closeMenus();
    if (e.key === "ArrowDown") { e.preventDefault(); btns[(i + 1) % btns.length]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length]?.focus(); }
  });
  return menu;
}
export function closeMenus() { document.querySelectorAll(".menu").forEach((m) => { m._cleanup?.(); m.remove(); }); }

// プルダウン（自前）。OS標準の <select> は開いたときの一覧の色をCSSで変えられない（白地＋青の選択色になる）ため、
// 一覧も含めてHubの配色で描く。options: [{value, label}]。キーボード（↑↓・Enter・Esc・頭文字）に対応。
export function selectBox({ options, value, onChange, labelledBy, labelFor }) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "select";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  if (labelledBy) btn.setAttribute("aria-labelledby", labelledBy);
  btn.innerHTML = `<span class="select-value"></span><svg class="icon select-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;
  let current = value;
  const show = () => {
    // 一覧に無い値（例: 拡大率 137%）は labelFor で表示を作る。無ければ先頭の項目を出す
    const o = options.find((x) => String(x.value) === String(current));
    btn.querySelector(".select-value").textContent = o ? o.label : labelFor ? labelFor(current) : (options[0]?.label ?? "");
  };
  show();

  btn.addEventListener("click", () => {
    if (btn.getAttribute("aria-expanded") === "true") return closeMenus();
    closeMenus();
    const list = document.createElement("div");
    list.className = "menu listbox";
    list.setAttribute("role", "listbox");
    for (const o of options) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "option");
      const sel = String(o.value) === String(current);
      b.setAttribute("aria-selected", String(sel));
      b.innerHTML = `<svg class="icon check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg><span></span>`;
      b.querySelector("span").textContent = o.label;
      b.addEventListener("click", () => {
        current = o.value;
        show();
        closeMenus();
        btn.focus();
        onChange?.(o.value);
      });
      list.append(b);
    }
    document.body.append(list);
    btn.setAttribute("aria-expanded", "true");
    const r = btn.getBoundingClientRect();
    list.style.minWidth = `${r.width}px`;
    const lh = list.getBoundingClientRect().height;
    const below = innerHeight - r.bottom - 6;
    list.style.left = `${Math.max(4, Math.min(r.left, innerWidth - list.offsetWidth - 4))}px`;
    list.style.top = `${below >= lh || below >= r.top ? r.bottom + 4 : Math.max(4, r.top - lh - 4)}px`;
    list.style.maxHeight = `${Math.max(120, below >= lh ? below : r.top - 8)}px`;
    (list.querySelector('[aria-selected="true"]') || list.querySelector("button")).focus();
    const outside = (e) => { if (!list.contains(e.target) && e.target !== btn && !btn.contains(e.target)) closeMenus(); };
    setTimeout(() => document.addEventListener("pointerdown", outside), 0);
    list._cleanup = () => { document.removeEventListener("pointerdown", outside); btn.setAttribute("aria-expanded", "false"); };
    list.addEventListener("keydown", (e) => {
      const items = [...list.querySelectorAll("button")];
      const i = items.indexOf(document.activeElement);
      if (e.key === "Escape" || e.key === "Tab") { closeMenus(); btn.focus(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(items.length - 1, i + 1)]?.focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(0, i - 1)]?.focus(); }
      else if (e.key.length === 1) {
        const hit = items.find((x, j) => j > i && x.textContent.toLowerCase().startsWith(e.key.toLowerCase()))
          || items.find((x) => x.textContent.toLowerCase().startsWith(e.key.toLowerCase()));
        hit?.focus();
      }
    });
  });
  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); btn.click(); }
  });
  btn.setValue = (v) => { current = v; show(); };
  return btn;
}
