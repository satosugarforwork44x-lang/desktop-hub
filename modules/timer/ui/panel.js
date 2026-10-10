// timer/ui/panel.js — タイマー。プリセットを押せば始まる。残り時間はバーにも出る（終了の音はバーが鳴らす）
import { icons } from "/ui/js/icons.js";
import { createFocusRing } from "./focus.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  let s = null;          // api.state() の値
  let base = 0;          // s を受け取った時刻（ローカルで数えるため）

  el.innerHTML = `
    <div class="timer">
      <div class="timer-dial">
        <svg viewBox="0 0 120 120" aria-hidden="true">
          <defs>
            <linearGradient id="timer-grad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" style="stop-color: rgb(var(--c1-rgb))"/>
              <stop offset=".5" style="stop-color: rgb(var(--c2-rgb))"/>
              <stop offset="1" style="stop-color: rgb(var(--c3-rgb))"/>
            </linearGradient>
          </defs>
          <circle class="timer-track" cx="60" cy="60" r="52"/>
          <circle class="timer-arc" cx="60" cy="60" r="52" pathLength="1000"/>
        </svg>
        <canvas class="timer-particles" aria-hidden="true"></canvas>
        <div class="timer-read"><div class="timer-time">0:00</div><div class="timer-label"></div></div>
      </div>
      <div class="timer-ctrl">
        <button type="button" class="btn timer-pause"></button>
        <button type="button" class="btn ghost timer-reset"></button>
        <button type="button" class="btn timer-focus"></button>
      </div>
      <div class="timer-new">
        <input class="input timer-name" maxlength="40">
        <div class="timer-presets"></div>
        <div class="timer-custom">
          <input class="input timer-min" type="number" min="1" max="1440" step="1" inputmode="numeric">
          <span class="timer-unit"></span>
          <button type="button" class="btn timer-go"></button>
        </div>
      </div>
    </div>`;
  const $ = (q) => el.querySelector(q);
  $(".timer-name").placeholder = t("timer.labelHint");
  $(".timer-min").placeholder = "10";
  $(".timer-unit").textContent = t("timer.min");
  $(".timer-go").textContent = t("timer.start");
  $(".timer-reset").textContent = t("timer.reset");

  const start = async (min) => {
    try { set(await ctx.call("start", { minutes: min, label: $(".timer-name").value })); }
    catch (e) { ctx.toast(e.message, "error"); }
  };
  for (const m of [5, 15, 25, 50]) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "timer-preset";
    b.textContent = t("timer.nMin", { n: m });
    b.addEventListener("click", () => start(m));
    $(".timer-presets").append(b);
  }
  $(".timer-go").addEventListener("click", () => { const v = Number($(".timer-min").value); if (v > 0) start(v); });
  $(".timer-min").addEventListener("keydown", (e) => { if (e.key === "Enter") $(".timer-go").click(); });
  $(".timer-pause").addEventListener("click", async () => set(await ctx.call(s?.paused ? "resume" : "pause")));
  $(".timer-reset").addEventListener("click", async () => { await ctx.call("reset"); set(null); });

  // ---- フォーカスモード: 粒子のリングにして、ほかの操作を隠す ----
  let ring = null;
  let focus = false;
  try { focus = localStorage.getItem("hub.timer.focus") === "1"; } catch { /* 保存できない環境 */ }
  const focusBtn = ctx.addTool(icons.focus, t("timer.focus"), () => setFocus(!focus));
  const focusMain = $(".timer-focus");
  focusMain.addEventListener("click", () => setFocus(!focus));
  // バーの残り時間を右クリック →「フォーカスモード」や、別の窓からの切り替えにも追いつく
  addEventListener("storage", (e) => { if (e.key === "hub.timer.focus") setFocus(e.newValue === "1"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && focus) setFocus(false); });
  function setFocus(on) {
    focus = on;
    focusMain.innerHTML = `${on ? icons.close : icons.focus}<span></span>`;
    focusMain.querySelector("span").textContent = t(on ? "timer.focusExit" : "timer.focus");
    focusMain.classList.toggle("on", on);
    try { localStorage.setItem("hub.timer.focus", on ? "1" : "0"); } catch { /* 同上 */ }
    focusBtn.setAttribute("aria-pressed", String(on));
    $(".timer").classList.toggle("focus", on);
    if (on) { ring ||= createFocusRing($(".timer-particles")); ring.start(); }
    else ring?.stop();
    draw();
  }

  function set(v) { s = v; base = Date.now(); draw(); }

  function remain() {
    if (!s) return 0;
    return s.paused ? s.remain : Math.max(0, s.remain - (Date.now() - base) / 1000);
  }
  function draw() {
    const r = remain();
    const sec = Math.ceil(r);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), ss = sec % 60;
    const p = (n) => String(n).padStart(2, "0");
    $(".timer-time").textContent = h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
    $(".timer-label").textContent = !s ? t("timer.idle") : r <= 0 ? t("timer.done") : s.paused ? t("timer.paused") : (s.label || "");
    $(".timer-arc").style.strokeDashoffset = String(s ? 1000 * (1 - r / s.total) : 1000);
    const root = $(".timer");
    ring?.update(s ? r / s.total : 1, !s ? "idle" : r <= 0 ? "done" : s.paused ? "paused" : "running");
    root.classList.toggle("running", !!s && !s.paused && r > 0);
    root.classList.toggle("done", !!s && r <= 0);
    root.classList.toggle("idle", !s);
    $(".timer-reset").hidden = !s;
    $(".timer-pause").hidden = !s || r <= 0;
    $(".timer-pause").textContent = s?.paused ? t("timer.resume") : t("timer.pause");
    ctx.setStatus(s && r > 0 ? t("timer.ends", { at: new Date(Date.now() + r * 1000).toLocaleTimeString(document.documentElement.lang === "en" ? "en-US" : "ja-JP", { hour: "2-digit", minute: "2-digit" }) }) : "");
  }

  set(await ctx.call("state"));
  setFocus(focus);
  setInterval(draw, 250);
  // バーや別の窓で操作されたときに追いつく
  setInterval(async () => { try { set(await ctx.call("state")); } catch { /* 終了時など */ } }, 5000);
}
