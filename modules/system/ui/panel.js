// system/ui/panel.js — PC モニター。1 秒ごとに測って、直近 1 分を小さなグラフで見せる
const N = 60;

export async function mount(el, ctx) {
  const t = ctx.t;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./system.css", import.meta.url).href;
  document.head.append(css);

  el.innerHTML = `
    <div class="sm">
      <div class="sm-grid"></div>
      <section class="sm-sec"><h2 class="sm-h"></h2><div class="sm-top"></div></section>
      <section class="sm-sec sm-opts">
        <label class="sm-opt"><span class="sm-opt-l"></span><input class="sm-host" spellcheck="false" maxlength="253"></label>
        <div class="set-switch"><span class="sm-bar-l"></span><button type="button" class="switch sm-bar" role="switch"><span class="knob"></span></button></div>
        <p class="set-note sm-note"></p>
      </section>
    </div>`;
  const $ = (s) => el.querySelector(s);
  $(".sm-h").textContent = t("sys.top");
  $(".sm-opt-l").textContent = t("sys.pingHost");
  $(".sm-bar-l").textContent = t("sys.onBar");
  $(".sm-note").textContent = t("sys.note");

  // ---------- カード ----------
  const cards = {};
  function card(id, label) {
    const c = document.createElement("div");
    c.className = "sm-card";
    c.dataset.id = id;
    c.innerHTML = `<div class="sm-label"></div><div class="sm-val"></div><div class="sm-sub"></div><canvas class="sm-spark"></canvas>`;
    c.querySelector(".sm-label").textContent = label;
    $(".sm-grid").append(c);
    cards[id] = { el: c, hist: [], hist2: [] };
    return cards[id];
  }
  card("cpu", "CPU");
  card("mem", t("sys.mem"));
  card("gpu", "GPU");
  card("disk", t("sys.disk"));
  card("net", t("sys.net"));
  card("ping", "Ping");

  const set = (id, val, sub, warn = false) => {
    const c = cards[id].el;
    c.querySelector(".sm-val").textContent = val;
    c.querySelector(".sm-sub").textContent = sub;
    c.classList.toggle("warn", warn);
  };
  const push = (id, v, v2) => {
    const k = cards[id];
    k.hist.push(v); if (k.hist.length > N) k.hist.shift();
    if (v2 !== undefined) { k.hist2.push(v2); if (k.hist2.length > N) k.hist2.shift(); }
    spark(k);
  };

  // ---------- 小さなグラフ（テーマのグラデーション） ----------
  const cs = getComputedStyle(document.documentElement);
  const [c1, c2, c3] = ["--c1-rgb", "--c2-rgb", "--c3-rgb"].map((k) => cs.getPropertyValue(k).trim());
  function spark(k) {
    const cv = k.el.querySelector(".sm-spark");
    const dpr = devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w) return;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const fixed = k.el.dataset.id === "cpu" || k.el.dataset.id === "mem" || k.el.dataset.id === "gpu";
    const all = [...k.hist, ...k.hist2].filter((v) => v != null);
    const max = fixed ? 100 : Math.max(1, ...all) * 1.15;
    const line = (hist, alpha, fill) => {
      if (hist.length < 2) return;
      const x = (i) => w - (hist.length - 1 - i) * (w / (N - 1));
      const y = (v) => h - 2 - ((v ?? 0) / max) * (h - 4);
      const grad = g.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, `rgba(${c1}, ${alpha})`); grad.addColorStop(0.5, `rgba(${c2}, ${alpha})`); grad.addColorStop(1, `rgba(${c3}, ${alpha})`);
      g.beginPath();
      hist.forEach((v, i) => (i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v))));
      g.strokeStyle = grad; g.lineWidth = 1.6; g.lineJoin = "round"; g.stroke();
      if (fill) {
        g.lineTo(x(hist.length - 1), h); g.lineTo(x(0), h); g.closePath();
        const f = g.createLinearGradient(0, 0, 0, h);
        f.addColorStop(0, `rgba(${c2}, .28)`); f.addColorStop(1, `rgba(${c2}, 0)`);
        g.fillStyle = f; g.fill();
      }
    };
    line(k.hist2, 0.45, false);   // 2 本目（上り・書き込み）は薄く
    line(k.hist, 1, true);
  }

  // ---------- 表示の形 ----------
  const gb = (b) => `${(b / 1073741824).toFixed(b >= 107374182400 ? 0 : 1)} GB`;
  const rate = (bps) => {   // 通信は bit/s（回線の速さと同じ単位）
    const b = bps * 8;
    return b >= 1e9 ? `${(b / 1e9).toFixed(2)} Gbps` : b >= 1e6 ? `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)} Mbps` : `${Math.round(b / 1e3)} kbps`;
  };
  const mbs = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(b >= 104857600 ? 0 : 1)} MB/s` : `${Math.round(b / 1024)} KB/s`);

  async function tick() {
    let s;
    try { s = await ctx.call("sample"); } catch (e) { ctx.setStatus(e.message); return; }
    set("cpu", `${Math.round(s.cpu)}%`, [t("sys.threads", { n: s.cores }), s.freq ? `${(s.freq / 1000).toFixed(2)} GHz` : ""].filter(Boolean).join(" · "), s.cpu >= 90);
    push("cpu", s.cpu);
    set("mem", `${Math.round(s.mem.pct)}%`, `${gb(s.mem.used)} / ${gb(s.mem.total)}`, s.mem.pct >= 90);
    push("mem", s.mem.pct);
    const gpu = s.gpu?.[0];
    if (gpu) {
      set("gpu", gpu.util != null ? `${Math.round(gpu.util)}%` : "—",
        [gpu.memUsed != null ? `VRAM ${(gpu.memUsed / 1024).toFixed(1)}/${(gpu.memTotal / 1024).toFixed(0)} GB` : "", gpu.temp != null ? `${Math.round(gpu.temp)}°C` : "",
          gpu.power != null ? `${Math.round(gpu.power)} W` : ""].filter(Boolean).join(" · "), (gpu.temp ?? 0) >= 85);
      cards.gpu.el.title = gpu.name;
      cards.gpu.el.classList.remove("off");
      push("gpu", gpu.util);
    } else {
      set("gpu", "—", t("sys.noGpu"));
      cards.gpu.el.classList.add("off");
    }
    set("disk", mbs(s.io.read + s.io.write), `${s.disk.drive} ${t("sys.free", { v: s.disk.free != null ? gb(s.disk.free) : "—" })}`);
    cards.disk.el.title = `Read ${mbs(s.io.read)} · Write ${mbs(s.io.write)}`;
    push("disk", s.io.read, s.io.write);
    set("net", `↓ ${rate(s.io.down)}`, `↑ ${rate(s.io.up)}`);
    push("net", s.io.down, s.io.up);
    const up = s.uptime;
    ctx.setStatus(t("sys.uptime", { d: Math.floor(up / 86400), h: Math.floor((up % 86400) / 3600), m: Math.floor((up % 3600) / 60) })
      + (s.battery ? ` · ${t("sys.battery", { p: s.battery.pct })}${s.battery.plugged ? " ⚡" : ""}` : ""));
  }

  // Ping: 応答時間・ゆらぎ（ジッター）・届かなかった割合を直近 30 回で
  const pings = [];
  async function pingTick() {
    const r = await ctx.call("ping").catch(() => ({ ms: null }));
    pings.push(r.ms); if (pings.length > 30) pings.shift();
    const ok = pings.filter((v) => v != null);
    const loss = Math.round((100 * (pings.length - ok.length)) / pings.length);
    const jit = ok.length > 1 ? ok.slice(1).reduce((a, v, i) => a + Math.abs(v - ok[i]), 0) / (ok.length - 1) : 0;
    set("ping", r.ms != null ? `${r.ms < 10 ? r.ms.toFixed(1) : Math.round(r.ms)} ms` : "—",
      `${t("sys.jitter", { v: jit.toFixed(1) })} · ${t("sys.loss", { v: loss })}`, loss >= 10 || (r.ms ?? 0) >= 100);
    cards.ping.el.title = r.host || "";
    push("ping", r.ms);
  }

  async function topTick() {
    const rows = await ctx.call("top", { n: 6 }).catch(() => []);
    const box = $(".sm-top");
    box.replaceChildren();
    const max = Math.max(1, ...rows.map((r) => r.cpu));
    for (const r of rows) {
      const d = document.createElement("div");
      d.className = "sm-proc";
      d.innerHTML = `<span class="sm-pname"></span><span class="sm-pbar"><i></i></span><span class="sm-pcpu"></span><span class="sm-pmem"></span>`;
      d.querySelector(".sm-pname").textContent = r.count > 1 ? `${r.name} ×${r.count}` : r.name;
      d.querySelector(".sm-pbar i").style.width = `${(100 * r.cpu) / max}%`;
      d.querySelector(".sm-pcpu").textContent = `${r.cpu.toFixed(1)}%`;
      d.querySelector(".sm-pmem").textContent = gb(r.mem);
      box.append(d);
    }
  }

  // ---------- 設定 ----------
  let prefs = await ctx.call("prefs");
  const host = $(".sm-host");
  host.value = prefs.pingHost;
  host.addEventListener("change", async () => {
    try { prefs = await ctx.call("set_prefs", { pingHost: host.value }); pings.length = 0; cards.ping.hist = []; }
    catch (e) { ctx.toast(e.message, "error"); host.value = prefs.pingHost; }
  });
  const sw = $(".sm-bar");
  const showSw = () => { sw.setAttribute("aria-checked", String(prefs.bar)); sw.setAttribute("aria-label", t("sys.onBar")); };
  sw.addEventListener("click", async () => { prefs = await ctx.call("set_prefs", { bar: !prefs.bar }); showSw(); });
  showSw();

  // 見えていないときは測らない（負荷を見る道具が負荷にならないように）
  const loops = [];
  function start() {
    if (loops.length) return;
    tick(); pingTick(); topTick();
    loops.push(setInterval(tick, 1000), setInterval(pingTick, 2000), setInterval(topTick, 3000));
  }
  function stop() { loops.splice(0).forEach(clearInterval); }
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  start();
}
