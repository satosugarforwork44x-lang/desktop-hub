// bar.js — 画面の端の細いバー。マウスを乗せると広がり、モジュールのタイルが並ぶ
import { api, call, host, isNative, PARAMS, toast } from "./hub.js";
import { icons } from "./icons.js";
import "./theme.js";
import { t, translateDom, localize, LANG } from "./i18n.js";
import { listTiles, arrange } from "./tiles.js";

const $ = (s) => document.querySelector(s);
const dock = ["top", "bottom", "left", "right"].includes(PARAMS.get("dock")) ? PARAMS.get("dock") : "top";
const vertical = dock === "left" || dock === "right";
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
translateDom();
let pinned = false;
let collapseTimer = null;
let modules = [];
let labelsMode = "auto";   // hub.config.json の bar.labels: auto（入りきらなければアイコンだけ）/ icons / full
let barConf = {};          // hub.config.json の bar（length: "auto" なら中身に合わせて伸びる / tiles: 並びと非表示）
let statusMods = [];        // バーに状態（次の予定など）を出すモジュール
const statusData = new Map();

$("#bar").classList.add(`dock-${dock}`);
if (vertical) $("#bar").classList.add("vertical");
$("#pin").innerHTML = icons.pin;
$("#quit").innerHTML = icons.power;

// ---- 時計 ----
function tick() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  $("#time").textContent = `${p(d.getHours())}:${p(d.getMinutes())}`;
  $("#date").textContent = vertical ? `${p(d.getMonth() + 1)}/${p(d.getDate())}` : LANG === "ja"
    ? `${p(d.getMonth() + 1)}/${p(d.getDate())}(${"日月火水木金土"[d.getDay()]})`
    : `${DOW[d.getDay()]} ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}
tick();
setInterval(tick, 1000 * 15);

// ---- 広げる・畳む ----
async function setExpanded(on) {
  clearTimeout(collapseTimer);
  if (!on && (pinned || document.querySelector(".tile-input"))) return; // 入力中は畳まない
  document.body.classList.toggle("collapsed", !on);
  if (isNative()) await host.bar({ expanded: on }).catch(() => {});
  if (on) { refreshOpenState(); autoLength(); }
}
document.body.addEventListener("mouseenter", () => setExpanded(true));
document.body.addEventListener("mouseleave", () => {
  collapseTimer = setTimeout(() => setExpanded(false), 700); // すぐ畳むと操作しにくいので少し待つ
});
// ブラウザでの確認表示では常に広げておく
if (!isNative()) document.body.classList.remove("collapsed");

// ---- 起動アニメーション（約2秒）----
// ① 畳んだバー（光る線）が中央から伸びる → ② バーを広げ、地の色が満ちる → ③ 中身が順に浮かぶ → ④ 光が一度横切る → 畳む
// 窓は透明にできないので、線の段階は「畳んだ窓（細い線）」のまま行い、広げるのは線が伸び切ってから
if (PARAMS.get("intro") === "1") {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let hovering = false;
  document.body.addEventListener("mouseenter", () => { hovering = true; }, { once: true });
  const open = async () => {
    document.body.classList.remove("intro-line");
    document.body.classList.add("intro");
    await setExpanded(true);
    setTimeout(() => {
      document.body.classList.remove("intro");
      if (!hovering && !pinned) setExpanded(false);
    }, reduce ? 700 : 1900);
  };
  if (reduce) open();
  else {
    document.body.classList.add("intro-line");
    setTimeout(open, 420);
  }
}

$("#pin").addEventListener("click", async () => {
  pinned = !pinned;
  $("#pin").setAttribute("aria-pressed", String(pinned));
  $("#pin").title = t(pinned ? "bar.unpin" : "bar.pin");
  await host.bar({ pinned }).catch(() => {});
});
$("#quit").addEventListener("click", () => host.quit());

// 前回 📌 で広げたままにしていたら、その状態で始める
host.bar({}).then((st) => {
  if (!st?.pinned) return;
  pinned = true;
  $("#pin").setAttribute("aria-pressed", "true");
  $("#pin").title = t("bar.unpin");
  if (PARAMS.get("intro") !== "1") setExpanded(true);  // 起動アニメーションのときは、開いたまま畳まない
}).catch(() => {});

// ---- タイル ----
async function openPanel(pid) {
  try {
    const r = await host.togglePanel(pid);
    // ブラウザ確認表示では、別タブでパネルを開く
    if (!isNative() && r.url) window.open(r.url, pid, "width=340,height=480");
    refreshOpenState();
  } catch (e) {
    toast(e.message, "error");
  }
}

function tile(pid, label, icon, title) {
  const b = document.createElement("button");
  b.className = "tile";
  b.dataset.pid = pid;
  b.title = title || label;
  b.setAttribute("aria-label", label);
  b.innerHTML = `${icon}<span class="tile-label"></span>`;
  b.querySelector("span").textContent = label;
  b.addEventListener("click", () => openPanel(pid));
  return b;
}

async function render() {
  const { tiles: all, registry: reg } = await listTiles();
  // tile.place = "end" のもの（設定など）は、タイルの列ではなく右端（下端）の小さなボタンにする
  const endMods = reg.modules.map(localize).filter((m) => m.hub?.window === "panel" && m.hub?.tile?.place === "end");
  document.querySelectorAll(".bar-end .end-mod").forEach((x) => x.remove());
  for (const m of endMods) {
    const b = document.createElement("button");
    b.className = "icon-btn end-mod tile";
    b.dataset.pid = m.id;
    b.title = m.name;
    b.setAttribute("aria-label", m.name);
    b.innerHTML = icons[m.hub?.tile?.icon] || icons.tool;
    b.addEventListener("click", () => openPanel(m.id));
    $("#pin").before(b);
  }
  // 並び・非表示は設定（バーのタイル）に従う。フォルダ窓を足す「＋」は最後に
  const tiles = $("#tiles");
  tiles.replaceChildren();
  for (const x of arrange(all, barConf.tiles)) {
    if (!x.hidden) tiles.append(tile(x.pid, x.label, x.icon, x.title));
  }
  if (all.some((x) => x.module === "folders")) {
    const group = document.createElement("div");
    group.className = "tile-group";
    group.append(addRegistryButton(group));
    tiles.append(group);
  }
  modules = all;

  statusMods = reg.modules.map(localize).filter((m) => m.hub?.status?.fn && !m.errors.length);
  pollStatus(true);
  fit();
  autoLength();

  const errs = [...reg.errors, ...reg.modules.flatMap((m) => m.errors.map((e) => `${m.id}: ${e}`))];
  $("#warn").hidden = errs.length === 0;
  $("#warn").title = errs.join("\n");
  refreshOpenState();
}

// 「＋」でその場に名前を入力して新しいレジストリ（フォルダ窓）を作る
function addRegistryButton(group) {
  const b = document.createElement("button");
  b.className = "icon-btn";
  b.title = t("bar.addFolder");
  b.setAttribute("aria-label", t("bar.addFolder"));
  b.innerHTML = icons.plus;
  b.addEventListener("click", () => {
    const input = document.createElement("input");
    input.className = "tile-input";
    input.placeholder = t("bar.folderPlaceholder");
    b.replaceWith(input);
    input.focus();
    let finished = false; // Enter と blur の二重実行を防ぐ
    const done = async (ok) => {
      if (finished) return;
      finished = true;
      const name = input.value.trim();
      input.remove();
      if (ok && name) {
        try {
          await call("folders", "create_registry", { name });
          await render();
          openPanel(`folders:${name}`);
        } catch (e) { toast(e.message, "error"); await render(); }
      } else {
        group.append(addRegistryButton(group));
      }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(false));
  });
  return b;
}

// タイルが入りきらないときは、マウスホイールで横にスクロールできるようにする
$("#tiles").addEventListener("wheel", (e) => {
  if (vertical) return;
  e.preventDefault();
  $("#tiles").scrollLeft += e.deltaY;
}, { passive: false });

async function refreshOpenState() {
  try {
    const open = new Set(await host.openPanels());
    document.querySelectorAll(".tile").forEach((t) => t.classList.toggle("open", open.has(t.dataset.pid)));
  } catch { /* 起動直後など */ }
}
setInterval(() => { if (!document.body.classList.contains("collapsed")) refreshOpenState(); }, 2000);

// ---- 状態（次の予定など）: モジュールの status() を定期的に呼んでバーに出す ----
// status() の返り値: { icon, prefix, at: "YYYY-MM-DDTHH:MM", text, detail, live } または null
const lastPoll = new Map();   // モジュール id → 最後に status() を呼んだ時刻
async function pollStatus(force = false) {
  const now = Date.now();
  let changed = false;
  for (const m of statusMods) {
    const every = Math.max(5, Number(m.hub.status.every) || 60) * 1000;
    if (!force && now - (lastPoll.get(m.id) || 0) < every - 500) continue;
    lastPoll.set(m.id, now);
    const key = (v) => JSON.stringify(v ? { ...v, _at: 0, remain: v.paused ? v.remain : 0 } : null);   // 数え進んだだけの差は無視
    const before = key(statusData.get(m.id));
    try { const v = await call(m.id, m.hub.status.fn); v ? statusData.set(m.id, { ...v, _at: Date.now() }) : statusData.delete(m.id); }
    catch { statusData.delete(m.id); }
    const after = statusData.get(m.id);
    if (before !== key(after)) changed = true;
  }
  if (changed || force) renderStatus();
}
function relTime(at, live) {
  if (live) return t("bar.status.now");
  const mins = Math.round((new Date(at) - new Date()) / 60000);
  return mins >= 0 && mins < 60 ? t("bar.status.in", { m: mins }) : "";
}
function renderStatus() {
  const box = $("#status");
  box.replaceChildren();
  for (const m of statusMods) {
    const s = statusData.get(m.id);
    if (!s) continue;
    const b = document.createElement("button");
    b.className = "chip";
    b.addEventListener("click", () => openPanel(m.id));
    if (s.countdown) { countdownChip(b, s); box.append(b); continue; }
    if (s.metric) {   // 数値だけの表示（例: PC モニターの CPU・メモリ）
      b.classList.add("metric");
      b.innerHTML = `${icons[s.icon] || icons.tool}`;
      for (const [k, v] of s.items || []) {
        const x = document.createElement("span");
        x.className = "chip-metric";
        x.innerHTML = `<span class="chip-prefix"></span><span class="chip-time"></span>`;
        x.querySelector(".chip-prefix").textContent = k;
        x.querySelector(".chip-time").textContent = v;
        b.append(x);
      }
      b.title = (s.items || []).map(([k, v]) => `${k} ${v}`).join("  ");
      b.setAttribute("aria-label", b.title);
      box.append(b);
      continue;
    }
    if (s.live) b.classList.add("live");
    const d = new Date(s.at);
    const today = new Date().toDateString() === d.toDateString();
    const p = (n) => String(n).padStart(2, "0");
    const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
    const wd = d.toLocaleDateString(LANG === "ja" ? "ja-JP" : "en-US", { weekday: "short" });
    const when = today ? hm : LANG === "ja" ? `${d.getMonth() + 1}/${d.getDate()}(${wd}) ${hm}` : `${wd} ${hm}`;
    const rel = relTime(s.at, s.live);
    b.innerHTML = `${icons[s.icon] || icons.tool}<span class="chip-prefix"></span><span class="chip-time"></span><span class="chip-text"></span><span class="chip-rel"></span>`;
    b.querySelector(".chip-prefix").textContent = s.prefix || "";
    b.querySelector(".chip-time").textContent = vertical ? hm : when;
    b.querySelector(".chip-text").textContent = s.text || "";
    b.querySelector(".chip-rel").textContent = rel;
    b.title = [`${s.prefix ? s.prefix + " " : ""}${when}  ${s.text || ""}`, s.detail, rel].filter(Boolean).join("\n");
    b.setAttribute("aria-label", b.title);
    box.append(b);
  }
  box.hidden = !box.childElementCount;
  fit();
  autoLength();
}
setInterval(() => pollStatus(), 5 * 1000);

// ---- 残り時間の表示（タイマーなど countdown: true の状態）。1 秒ごとに手元で数える ----
const rang = new Set();        // 終了音を鳴らした end（同じ終了で何度も鳴らさない）
function countdownChip(b, s) {
  b.classList.add("countdown");
  b.innerHTML = `${icons[s.icon] || icons.tool}<span class="chip-prefix"></span><span class="chip-time"></span>`;
  b.querySelector(".chip-prefix").textContent = vertical ? "" : (s.prefix || "");
  b._cd = s;
  drawCountdown(b);
}
function drawCountdown(b) {
  const s = b._cd;
  const left = s.paused ? s.remain : Math.max(0, s.remain - (Date.now() - s._at) / 1000);
  const sec = Math.ceil(left);
  const p = (n) => String(n).padStart(2, "0");
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  b.querySelector(".chip-time").textContent = sec <= 0 ? "0:00" : h ? `${h}:${p(m)}:${p(sec % 60)}` : `${m}:${p(sec % 60)}`;
  b.classList.toggle("paused", !!s.paused);
  b.classList.toggle("done", sec <= 0);
  b.title = [s.prefix, sec <= 0 ? t("timer.done") : s.paused ? t("timer.paused") : ""].filter(Boolean).join(" · ") || b.querySelector(".chip-time").textContent;
  b.setAttribute("aria-label", b.title);
  if (sec <= 0 && s.end && !rang.has(s.end)) {
    rang.add(s.end);
    // 終わった直後だけ鳴らす（再起動して古い「終了」を読んだときは鳴らさない）
    if (Date.now() / 1000 - s.end < 30) chime();
  }
}
setInterval(() => document.querySelectorAll(".chip.countdown").forEach(drawCountdown), 1000);
function chime() {
  try {
    const ac = new AudioContext();
    [0, 0.28, 0.56].forEach((d, i) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = "sine";
      o.frequency.value = i === 2 ? 1046.5 : 880;
      g.gain.setValueAtTime(0.0001, ac.currentTime + d);
      g.gain.exponentialRampToValueAtTime(0.18, ac.currentTime + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + d + 0.24);
      o.connect(g).connect(ac.destination);
      o.start(ac.currentTime + d);
      o.stop(ac.currentTime + d + 0.26);
    });
    setTimeout(() => ac.close(), 1200);
  } catch { /* 音が出せない環境 */ }
}

// ---- 入りきらないときの詰め方（横置きのとき）----
// 段階1: タイルの文字を隠してアイコンだけ → 段階2: 予定の件名と日付を隠す → 段階3: 「あと○分」も隠す。文字はツールチップで読める
function fit() {
  const bar = $("#bar");
  bar.classList.remove("icons-only", "tight", "tighter", "overflow");
  const over = () => (vertical ? $("#tiles").scrollHeight > $("#tiles").clientHeight + 1 : $("#tiles").scrollWidth > $("#tiles").clientWidth + 1);
  if (vertical || labelsMode === "icons") { bar.classList.add("icons-only"); if (over()) bar.classList.add("overflow"); return; }
  if (labelsMode === "full") { if (over()) bar.classList.add("overflow"); return; }
  if (over()) bar.classList.add("icons-only");
  if (over()) bar.classList.add("tight");
  if (over()) bar.classList.add("tighter");
  if (over()) bar.classList.add("overflow");   // それでも入らなければ横スクロール（端をぼかして続きがあると示す）
}
addEventListener("resize", () => fit());

// ---- 長さを中身に合わせる（設定の bar.length が "auto" のとき）----
// 文字を出した状態（設定が「アイコンだけ」ならアイコンの状態）で全部が入る長さを測り、Hub に知らせる。
// 画面の幅を超える分は Hub が画面の幅で止め、その中で fit() が詰める
let lenTimer = null;
function autoLength() {
  clearTimeout(lenTimer);
  lenTimer = setTimeout(() => {
    if ((barConf.length ?? "auto") !== "auto" || document.body.classList.contains("collapsed") || !isNative()) return;
    const bar = $("#bar"), tiles = $("#tiles");
    const keep = [...bar.classList].filter((c) => ["tight", "tighter", "overflow"].includes(c) || (c === "icons-only" && !vertical && labelsMode !== "icons"));
    bar.classList.remove(...keep);                     // 詰める前の、本来の長さで測る
    const need = vertical ? bar.offsetHeight - tiles.clientHeight + tiles.scrollHeight
      : bar.offsetWidth - tiles.clientWidth + tiles.scrollWidth;
    bar.classList.add(...keep);
    host.bar({ length: Math.ceil(need) + 4 }).catch(() => {});
  }, 120);
}

(async () => {
  try { barConf = (await host.config()).bar || {}; labelsMode = barConf.labels || "auto"; } catch { /* 既定のまま */ }
  await render();
})().catch((e) => toast(e.message, "error"));
