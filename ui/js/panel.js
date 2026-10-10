// panel.js — パネル窓の共通部分（見出し・畳む・閉じる・大きさ変更）。
// 中身はモジュールの ui/panel.js（L2）か、manifest の actions から作る汎用画面（L1）。
import { api, call, host, isNative, onNativeDrop, PARAMS, toast, contextMenu } from "./hub.js";
import { icons } from "./icons.js";
import "./theme.js";
import { t, translateDom, localize } from "./i18n.js";

const $ = (s) => document.querySelector(s);
const pid = PARAMS.get("id") || "";
const [moduleId, instance = null] = pid.split(/:(.*)/s);

translateDom();
$("#btn-close").innerHTML = icons.close;
$("#btn-collapse").innerHTML = icons.collapse;

// ---- 畳む／閉じる ----
let collapsed = false;
async function setCollapsed(on) {
  collapsed = on;
  document.body.classList.toggle("collapsed-panel", on);
  $("#btn-collapse").innerHTML = on ? icons.expand : icons.collapse;
  $("#btn-collapse").title = t(on ? "panel.expand" : "panel.collapse");
  await host.collapsePanel(pid, on).catch(() => {});
}
$("#btn-collapse").addEventListener("click", () => setCollapsed(!collapsed));
$("#title").addEventListener("dblclick", () => setCollapsed(!collapsed));
$("#btn-close").addEventListener("click", async () => {
  await host.closePanel(pid).catch(() => {});
  if (!isNative()) window.close();
});

// ---- 右下のつまみで大きさを変える（枠なし窓のため自前で実装） ----
const grip = $("#grip");
if (!isNative()) grip.hidden = true;
grip.addEventListener("pointerdown", (e) => {
  grip.setPointerCapture(e.pointerId);
  const sx = e.screenX, sy = e.screenY, sw = innerWidth, sh = innerHeight;
  let pending = null;
  const move = (ev) => {
    pending = [sw + ev.screenX - sx, sh + ev.screenY - sy];
    requestAnimationFrame(() => { if (pending) { host.resizePanel(pid, ...pending); pending = null; } });
  };
  const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", up);
});

// ---- モジュールに渡す道具 ----
function makeContext(mod) {
  return {
    id: pid,
    module: mod,
    instance,
    call: (fn, args) => call(moduleId, fn, args),
    host,
    toast,
    contextMenu,
    t,
    onNativeDrop,
    isNative,
    setStatus: (text) => { $("#foot").textContent = text || ""; },
    setTitle: (text) => { $("#title-name").textContent = text; document.title = text; },
    // 見出しにボタンを追加する（例: 元に戻す・更新）
    addTool(icon, title, onClick) {
      const b = document.createElement("button");
      b.className = "icon-btn";
      b.title = title;
      b.setAttribute("aria-label", title);
      b.innerHTML = icon;
      b.addEventListener("click", onClick);
      $("#tools").append(b);
      return b;
    },
  };
}

async function main() {
  const reg = await api("registry");
  const found = reg.modules.find((m) => m.id === moduleId);
  if (!found) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = t("panel.noModule", { id: moduleId });
    $("#body").replaceChildren(div);
    return;
  }
  const mod = localize(found);
  const title = instance ? instance : mod.name;
  $("#title-icon").innerHTML = icons[mod.hub?.tile?.icon] || icons.tool;
  $("#title-name").textContent = title;
  document.title = title;

  const st = await host.panelState(pid).catch(() => null);
  if (st?.collapsed) { collapsed = true; document.body.classList.add("collapsed-panel"); $("#btn-collapse").innerHTML = icons.expand; }

  const ctx = makeContext(mod);
  try {
    // ui があればモジュール独自の画面、無ければ actions から汎用画面を作る
    const ui = mod.ui ? await import(`${mod.ui}?t=${PARAMS.get("t")}`) : await import("./actions-panel.js");
    await ui.mount($("#body"), ctx);
  } catch (e) {
    console.error(e);
    $("#body").innerHTML = "";
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = t("panel.loadError", { msg: e.message });
    $("#body").append(div);
  }
}
main();
