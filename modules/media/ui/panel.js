// media/ui/panel.js — 動画と音楽のプレイヤー。再生は WebView2 の <video>（音楽も同じ要素で鳴らす）。
//   音楽のときは、テーマのグラデーション色で音に合わせて動く輪（スペクトラム）を描く
import { TOKEN } from "/ui/js/hub.js";
import { icons } from "/ui/js/icons.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./media.css", import.meta.url).href;
  document.head.append(css);

  el.innerHTML = `
    <div class="mp">
      <div class="mp-stage">
        <video class="mp-video" playsinline preload="metadata"></video>
        <div class="mp-art"><canvas></canvas><div class="mp-art-title"></div><div class="mp-art-sub"></div></div>
        <div class="mp-msg" hidden><p></p><div class="btn-row"></div></div>
        <div class="mp-empty drop"><div class="drop-ico"></div><div class="drop-text"></div><div class="drop-or"></div><button class="btn" type="button"></button></div>
      </div>
      <div class="mp-seek"><span class="mp-time">0:00</span><input class="mp-range mp-pos" type="range" min="0" max="1000" value="0"><span class="mp-dur">0:00</span></div>
      <div class="mp-ctrl">
        <button class="icon-btn" data-a="repeat"></button>
        <span class="mp-grow"></span>
        <button class="icon-btn" data-a="prev"></button>
        <button class="mp-play" data-a="play"></button>
        <button class="icon-btn" data-a="next"></button>
        <span class="mp-grow"></span>
        <button class="icon-btn" data-a="mute"></button>
        <input class="mp-range mp-vol" type="range" min="0" max="100" value="80">
        <button class="icon-btn" data-a="full"></button>
      </div>
      <div class="mp-listhead"><span class="mp-listtitle"></span><span class="mp-grow"></span>
        <button class="icon-btn" data-a="add"></button><button class="icon-btn" data-a="clear"></button></div>
      <div class="mp-list"></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const btn = (a) => el.querySelector(`[data-a="${a}"]`);
  const video = $(".mp-video");
  const pos = $(".mp-pos");
  const vol = $(".mp-vol");
  const tip = (a, ico, k) => { const b = btn(a); b.innerHTML = ico; b.title = t(k); b.setAttribute("aria-label", t(k)); };
  tip("prev", icons.skipBack, "media.prev"); tip("next", icons.skipFwd, "media.next");
  tip("add", icons.plus, "media.add"); tip("clear", icons.trash, "media.clear"); tip("full", icons.expand, "media.full");
  $(".mp-empty .drop-ico").innerHTML = icons.play;
  $(".mp-empty .drop-text").textContent = t("media.drop");
  $(".mp-empty .drop-or").textContent = t("action.or");
  $(".mp-empty .btn").textContent = t("action.pick");

  let st = { items: [], current: null, rev: 0, volume: 0.8, repeat: "all", ffmpeg: false };
  let cur = null;          // 今の項目

  // ---------- 再生リスト ----------
  function renderList() {
    const list = $(".mp-list");
    list.replaceChildren();
    $(".mp-listtitle").textContent = t("media.list", { n: st.items.length });
    for (const [i, it] of st.items.entries()) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "mp-item";
      if (cur?.key === it.key) row.classList.add("on");
      row.innerHTML = `<span class="mp-no"></span>${it.kind === "video" ? icons.video : icons.music}<span class="mp-name"></span><span class="mp-ext"></span>`;
      row.querySelector(".mp-no").textContent = String(i + 1);
      row.querySelector(".mp-name").textContent = it.name;
      row.querySelector(".mp-ext").textContent = it.ext.toUpperCase();
      row.title = it.path;
      row.addEventListener("click", () => play(it));
      row.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        ctx.contextMenu([
          { label: t("folders.reveal"), icon: icons.reveal, onClick: async () => ctx.host.revealPath(await ctx.call("reveal_path", { key: it.key })).catch((er) => ctx.toast(er.message, "error")) },
          { label: t("media.remove"), icon: icons.close, onClick: async () => { st = await ctx.call("remove", { key: it.key }); if (cur?.key === it.key) stop(); renderList(); } },
        ], e.clientX, e.clientY);
      });
      list.append(row);
    }
    el.querySelector(".mp").classList.toggle("empty", !st.items.length);
    btn("clear").disabled = !st.items.length;
  }

  // ---------- 再生 ----------
  const src = (it) => `/blob/media/${it.key}?t=${encodeURIComponent(TOKEN)}`;
  function play(it, autoplay = true) {
    cur = it;
    hideMsg();
    el.querySelector(".mp").dataset.kind = it.kind;
    $(".mp-art-title").textContent = it.name;
    $(".mp-art-sub").textContent = it.ext.toUpperCase();
    ctx.setTitle(it.name);
    video.src = src(it);
    if (autoplay) video.play().catch(() => {});
    ctx.call("set_current", { key: it.key }).catch(() => {});
    renderList();
    $(".mp-item.on")?.scrollIntoView({ block: "nearest" });
  }
  function stop() { cur = null; video.removeAttribute("src"); video.load(); ctx.setTitle(ctx.module.name); updateUi(); }
  function next(dir = 1, auto = false) {
    if (!st.items.length) return;
    if (auto && st.repeat === "one") { video.currentTime = 0; video.play(); return; }
    const i = st.items.findIndex((x) => x.key === cur?.key);
    const j = i + dir;
    if (auto && st.repeat === "off" && (j >= st.items.length)) { updateUi(); return; }
    play(st.items[(j + st.items.length) % st.items.length]);
  }
  video.addEventListener("ended", () => next(1, true));
  video.addEventListener("error", () => {
    if (!cur) return;
    showMsg(cur.native ? t("media.cantPlay") : t("media.needConvert", { ext: cur.ext.toUpperCase() }), !st.ffmpeg ? [] : [
      { label: t("media.convert"), primary: true, onClick: convert },
    ]);
    if (!st.ffmpeg) $(".mp-msg p").textContent += "\n" + t("media.noFfmpeg");
  });

  // 変換（ffmpeg）。終わったら変換後のファイルを再生する
  async function convert() {
    const key = cur.key;
    try {
      await ctx.call("convert", { key });
      showMsg(t("media.converting", { p: 0 }), []);
      const timer = setInterval(async () => {
        const s = await ctx.call("convert_status", { key }).catch(() => ({ state: "error", error: "" }));
        if (s.state === "running") { $(".mp-msg p").textContent = t("media.converting", { p: Math.round(s.progress * 100) }); return; }
        clearInterval(timer);
        if (s.state === "done") { await reload(); const it = st.items.find((x) => x.key === s.key); if (it) play(it); }
        else showMsg(`${t("media.convertFailed")}\n${s.error || ""}`.trim(), []);
      }, 700);
    } catch (e) { ctx.toast(e.message, "error", 6000); }
  }
  function showMsg(text, buttons) {
    const m = $(".mp-msg");
    m.hidden = false;
    m.querySelector("p").textContent = text;
    const row = m.querySelector(".btn-row");
    row.replaceChildren();
    for (const b of buttons) {
      const x = document.createElement("button");
      x.type = "button";
      x.className = b.primary ? "btn primary" : "btn";
      x.textContent = b.label;
      x.addEventListener("click", b.onClick);
      row.append(x);
    }
  }
  function hideMsg() { $(".mp-msg").hidden = true; }

  // ---------- 操作の見た目 ----------
  const fmt = (s) => {
    if (!Number.isFinite(s)) return "0:00";
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
  };
  const fill = (r) => r.style.setProperty("--p", `${(100 * (r.value - r.min)) / (r.max - r.min)}%`);
  let seeking = false;
  function updateUi() {
    const playing = !video.paused && !video.ended && !!cur;
    const b = btn("play");
    b.innerHTML = playing ? icons.pause : icons.play;
    b.title = t(playing ? "media.pause" : "media.play");
    b.setAttribute("aria-label", b.title);
    b.disabled = !st.items.length;
    if (!seeking) pos.value = video.duration ? Math.round((1000 * video.currentTime) / video.duration) : 0;
    fill(pos);
    $(".mp-time").textContent = fmt(video.currentTime);
    $(".mp-dur").textContent = fmt(video.duration);
    const r = btn("repeat");
    r.innerHTML = st.repeat === "one" ? icons.repeatOne : icons.repeat;
    r.setAttribute("aria-pressed", String(st.repeat !== "off"));
    r.title = t(`media.repeat.${st.repeat}`);
    r.setAttribute("aria-label", r.title);
    const m = btn("mute");
    m.innerHTML = video.muted || video.volume === 0 ? icons.mute : icons.volume;
    m.title = t(video.muted ? "media.unmute" : "media.mute");
    vol.value = Math.round((video.muted ? 0 : video.volume) * 100);
    fill(vol);
    btn("full").hidden = cur?.kind !== "video";
    ctx.setStatus(cur ? `${fmt(video.currentTime)} / ${fmt(video.duration)}` : "");
  }
  for (const ev of ["play", "pause", "timeupdate", "durationchange", "volumechange", "loadedmetadata", "emptied"]) video.addEventListener(ev, updateUi);

  btn("play").addEventListener("click", () => {
    if (!cur && st.items.length) return play(st.items.find((x) => x.key === st.current) || st.items[0]);
    video.paused ? video.play().catch(() => {}) : video.pause();
  });
  btn("prev").addEventListener("click", () => (video.currentTime > 3 ? (video.currentTime = 0) : next(-1)));
  btn("next").addEventListener("click", () => next(1));
  btn("repeat").addEventListener("click", async () => {
    st.repeat = { all: "one", one: "off", off: "all" }[st.repeat];
    ctx.call("set_prefs", { repeat: st.repeat }).catch(() => {});
    updateUi();
  });
  btn("mute").addEventListener("click", () => { video.muted = !video.muted; });
  btn("full").addEventListener("click", () => (document.fullscreenElement ? document.exitFullscreen() : video.requestFullscreen()).catch(() => {}));
  pos.addEventListener("input", () => { seeking = true; fill(pos); $(".mp-time").textContent = fmt((pos.value / 1000) * (video.duration || 0)); });
  pos.addEventListener("change", () => { if (video.duration) video.currentTime = (pos.value / 1000) * video.duration; seeking = false; });
  let volSave = null;
  vol.addEventListener("input", () => {
    video.muted = false;
    video.volume = vol.value / 100;
    clearTimeout(volSave);
    volSave = setTimeout(() => ctx.call("set_prefs", { volume: video.volume }).catch(() => {}), 400);
  });
  video.addEventListener("click", () => (video.paused ? video.play() : video.pause()));
  video.addEventListener("dblclick", () => btn("full").click());

  document.addEventListener("keydown", (e) => {
    if (e.target.matches?.("input:not([type=range]), textarea") || e.target.closest?.(".menu") || e.ctrlKey || e.metaKey) return;
    const k = e.key.toLowerCase();
    if (k === " " || k === "k") { e.preventDefault(); btn("play").click(); }
    else if (k === "arrowright") { e.preventDefault(); video.currentTime = Math.min(video.duration || 0, video.currentTime + 5); }
    else if (k === "arrowleft") { e.preventDefault(); video.currentTime = Math.max(0, video.currentTime - 5); }
    else if (k === "arrowup") { e.preventDefault(); video.volume = Math.min(1, video.volume + 0.05); }
    else if (k === "arrowdown") { e.preventDefault(); video.volume = Math.max(0, video.volume - 0.05); }
    else if (k === "n") next(1);
    else if (k === "p") next(-1);
    else if (k === "m") video.muted = !video.muted;
    else if (k === "f" && cur?.kind === "video") btn("full").click();
  });

  // ---------- 入れる ----------
  async function addPaths(paths, playFirst) {
    try {
      st = await ctx.call("add", { paths, play: playFirst });
      renderList();
      if (playFirst) { const it = st.items.find((x) => x.key === st.current); if (it) play(it); }
    } catch (e) { ctx.toast(e.message, "error"); }
  }
  async function pick() {
    if (!ctx.isNative()) {
      const p = window.prompt(t("action.promptPath"));
      if (p) addPaths([p.trim().replace(/^"|"$/g, "")], !cur);
      return;
    }
    const picked = await ctx.host.pickFiles(ctx.id).catch(() => null);
    if (picked?.length) addPaths(picked, !cur);
  }
  btn("add").addEventListener("click", pick);
  $(".mp-empty .btn").addEventListener("click", pick);
  btn("clear").addEventListener("click", async () => { st = await ctx.call("clear"); stop(); renderList(); });
  ctx.onNativeDrop((paths) => addPaths(paths, !cur || video.paused));
  el.addEventListener("dragover", (e) => { e.preventDefault(); el.querySelector(".mp").classList.add("over"); });
  el.addEventListener("dragleave", (e) => { if (!el.contains(e.relatedTarget)) el.querySelector(".mp").classList.remove("over"); });
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    el.querySelector(".mp").classList.remove("over");
    if (!ctx.isNative()) ctx.toast(t("action.browserDrop"), "error", 4500);
  });

  // 「プログラムから開く」や別の窓から入ったら追いつく
  async function reload() {
    const before = st;
    st = await ctx.call("state");
    renderList();
    return before;
  }
  setInterval(async () => {
    try {
      const s = await ctx.call("state");
      if (s.rev !== st.rev || s.current !== st.current) {
        const changedCurrent = s.current && s.current !== cur?.key && s.current !== st.current;
        st = s;
        renderList();
        if (changedCurrent) { const it = st.items.find((x) => x.key === st.current); if (it) play(it); }
      }
    } catch { /* 終了時など */ }
  }, 2000);

  // ---------- 音に合わせて動く輪（音楽のとき） ----------
  const art = $(".mp-art canvas");
  let analyser = null;
  function ensureAnalyser() {
    if (analyser) return;
    try {
      const ac = new AudioContext();
      const node = ac.createMediaElementSource(video);
      analyser = ac.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.8;
      node.connect(analyser).connect(ac.destination);
      video.addEventListener("play", () => ac.resume());
    } catch { analyser = null; }
  }
  video.addEventListener("play", ensureAnalyser, { once: true });
  const bins = new Uint8Array(1024);
  // 64 本の線に、40 Hz〜16 kHz を「対数」で割り当てる（耳の感じ方に近く、輪の全体が動く）
  const BANDS = Array.from({ length: 65 }, (_, k) => 40 * (16000 / 40) ** (k / 64));
  const level = new Float32Array(64);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function colors() {
    const cs = getComputedStyle(document.documentElement);
    return ["--c1-rgb", "--c2-rgb", "--c3-rgb"].map((k) => cs.getPropertyValue(k).trim());
  }
  const [c1, c2, c3] = colors();
  function drawArt() {
    requestAnimationFrame(drawArt);
    if (el.querySelector(".mp").dataset.kind === "video" || art.offsetParent === null) return;
    const dpr = devicePixelRatio || 1;
    const w = art.clientWidth, h = art.clientHeight;
    if (art.width !== Math.round(w * dpr)) { art.width = Math.round(w * dpr); art.height = Math.round(h * dpr); }
    const g = art.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const playing = analyser && !video.paused;
    if (playing) analyser.getByteFrequencyData(bins);
    for (let i = 0; i < 64; i++) {
      let v = 0;
      if (playing && !reduce) {
        const hz = 22050 / 1024;                                   // 1 つの bin の幅（44.1 kHz のとき）
        const lo = Math.max(1, Math.floor(BANDS[i] / hz)), hi = Math.max(lo + 1, Math.ceil(BANDS[i + 1] / hz));
        for (let j = lo; j < hi && j < 1024; j++) v = Math.max(v, bins[j]);
        v = Math.min(1, (v / 255) * (0.85 + i * 0.012));         // 高い音ほど小さく出るので少し持ち上げる
      }
      level[i] += (v - level[i]) * 0.35;
    }
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.26;
    const grad = g.createLinearGradient(cx - R * 1.6, cy + R * 1.6, cx + R * 1.6, cy - R * 1.6);
    grad.addColorStop(0, `rgb(${c1})`); grad.addColorStop(0.5, `rgb(${c2})`); grad.addColorStop(1, `rgb(${c3})`);
    // 中の円（ゆっくり呼吸する）
    const avg = level.reduce((a, b) => a + b, 0) / 64;
    g.globalAlpha = 0.16 + avg * 0.3;
    g.fillStyle = grad;
    g.beginPath(); g.arc(cx, cy, R * (0.86 + avg * 0.12), 0, Math.PI * 2); g.fill();
    // まわりの線（左右対称に 128 本）
    g.globalAlpha = 0.95;
    g.strokeStyle = grad;
    g.lineWidth = Math.max(2, R * 0.035);
    g.lineCap = "round";
    for (let i = 0; i < 128; i++) {
      const k = i < 64 ? i : 127 - i;
      const a = (i / 128) * Math.PI * 2 - Math.PI / 2;
      const len = R * (0.06 + level[k] * 0.75);
      g.beginPath();
      g.moveTo(cx + Math.cos(a) * (R + 4), cy + Math.sin(a) * (R + 4));
      g.lineTo(cx + Math.cos(a) * (R + 4 + len), cy + Math.sin(a) * (R + 4 + len));
      g.stroke();
    }
    g.globalAlpha = 1;
  }
  requestAnimationFrame(drawArt);

  // ---------- はじめ ----------
  st = await ctx.call("state");
  video.volume = st.volume;
  renderList();
  const first = st.items.find((x) => x.key === st.current);
  if (first) play(first, false);
  updateUi();
}
