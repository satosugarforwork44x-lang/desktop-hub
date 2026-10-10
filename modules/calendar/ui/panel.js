// calendar/ui/panel.js — これからの予定の一覧（読み取り専用）と、iCal URL の登録
import { icons } from "/ui/js/icons.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  const lang = document.documentElement.lang === "ja" ? "ja-JP" : "en-US";
  const root = document.createElement("div");
  root.className = "cal";
  el.append(root);

  ctx.addTool(icons.refresh, t("cal.refresh"), () => load(true));
  ctx.addTool(icons.link, t("cal.addUrl"), () => showSetup(true));

  const dayKey = (iso) => iso.slice(0, 10);
  const time = (iso) => iso.slice(11, 16);
  function dayLabel(key) {
    const d = new Date(`${key}T00:00`);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((d - today) / 86400000);
    const rel = diff === 0 ? t("cal.today") : diff === 1 ? t("cal.tomorrow") : "";
    const date = d.toLocaleDateString(lang, { month: "short", day: "numeric", weekday: "short" });
    return rel ? `${rel} · ${date}` : date;
  }

  function showSetup(open) {
    root.querySelector(".cal-setup")?.remove();
    if (!open) return;
    const box = document.createElement("form");
    box.className = "cal-setup";
    box.innerHTML = `
      <label class="field"><span></span><input type="url" required placeholder="https://calendar.google.com/…/basic.ics"></label>
      <p class="hint"></p>
      <div class="btn-row"><button class="btn primary" type="submit"></button><button class="btn" type="button"></button></div>`;
    box.querySelector("span").textContent = t("cal.urlLabel");
    box.querySelector(".hint").textContent = t("cal.urlHint");
    const [save, cancel] = box.querySelectorAll("button");
    save.textContent = t("cal.save");
    cancel.textContent = t("cal.cancel");
    cancel.addEventListener("click", () => showSetup(false));
    box.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = box.querySelector("input").value.trim();
      try {
        const cur = (await ctx.call("upcoming", { days: 1 })).urls || [];
        await ctx.call("set_urls", { urls: [...cur, url] });
        showSetup(false);
        load(true);
      } catch (err) { ctx.toast(err.message, "error", 5000); }
    });
    root.prepend(box);
    box.querySelector("input").focus();
  }

  async function load(refresh = false) {
    let r;
    try { r = await ctx.call("upcoming", { days: 7, refresh }); }
    catch (e) { ctx.toast(e.message, "error", 5000); return; }
    root.querySelectorAll(".cal-list, .empty").forEach((x) => x.remove());
    if (!r.configured) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = t("cal.notConfigured");
      root.append(empty);
      showSetup(true);
      ctx.setStatus("");
      return;
    }
    const list = document.createElement("div");
    list.className = "cal-list";
    let last = "";
    const now = new Date().toISOString().slice(0, 16);
    for (const e of r.events) {
      const k = dayKey(e.start);
      if (k !== last) {
        const h = document.createElement("div");
        h.className = "cal-day";
        h.textContent = dayLabel(k);
        list.append(h);
        last = k;
      }
      const row = document.createElement("div");
      row.className = "cal-ev";
      if (!e.allDay && e.start <= now && e.end > now) row.classList.add("live");
      const tm = document.createElement("span");
      tm.className = "cal-time";
      tm.textContent = e.allDay ? t("cal.allDay") : `${time(e.start)}`;
      const body = document.createElement("span");
      body.className = "cal-body";
      const ti = document.createElement("span");
      ti.className = "cal-title";
      ti.textContent = e.title;
      body.append(ti);
      if (e.location) {
        const lo = document.createElement("span");
        lo.className = "cal-loc";
        lo.textContent = e.location;
        body.append(lo);
      }
      row.append(tm, body);
      row.title = `${e.title}${e.location ? `\n${e.location}` : ""}`;
      list.append(row);
    }
    if (!r.events.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = t("cal.none");
      root.append(empty);
    }
    root.append(list);
    ctx.setStatus(r.error ? t("cal.offline") : t("cal.count", { n: r.events.length }));
  }

  setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
  await load();
}
