// tiles.js — バーに並べるタイルの一覧。バー（bar.js）と設定（並べ替え・表示）で同じものを使う。
//   ・設定（bar.tiles）の order の順に並べ、hidden に入っているものは出さない
//   ・order に無いもの（新しく入れたモジュールやフォルダ窓）は、既定の順で後ろに足す
import { api, call } from "./hub.js";
import { localize } from "./i18n.js";
import { icons } from "./icons.js";

// フォルダ窓のアイコン: 色付きのフォルダに頭文字（アイコンだけの表示でもどれか分かるように）
// 色は名前から決まる（同じ名前なら毎回同じ色）。テーマを問わず見分けやすい 8 色
const BADGE = ["#2FC6C0", "#4F7DF3", "#8D6CF2", "#E5679A", "#E8A33D", "#4FB37A", "#38BDF8", "#6E7C96"];
export function folderBadge(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  const letter = ([...name.trim()][0] || "?").toUpperCase();
  const esc = letter.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return `<span class="fbadge" style="--fc:${BADGE[h % BADGE.length]}">${icons.folderFill}<b>${esc}</b></span>`;
}

// 既定の順（単独の道具 → 窓が増えていくもの（フォルダ窓））。設定（tile.place = "end"）は右端に固定なので入れない
export async function listTiles() {
  const reg = await api("registry");
  const mods = reg.modules.map(localize)
    .filter((m) => (m.kind === "panel" || m.kind === "launcher") && m.hub?.window === "panel" && m.hub?.tile?.place !== "end");
  mods.sort((a, b) => Number(!!a.hub?.multi) - Number(!!b.hub?.multi));
  const out = [];
  for (const m of mods) {
    const icon = icons[m.hub?.tile?.icon] || icons.tool;
    if (m.hub?.multi) {
      try {
        for (const it of await call(m.id, "instances")) {
          out.push({ pid: `${m.id}:${it.id}`, label: it.label, icon: m.id === "folders" ? folderBadge(it.label) : icon,
            title: `${m.name}: ${it.label}`, module: m.id, folder: m.id === "folders" });
        }
      } catch (e) {
        out.push({ pid: m.id, label: m.name, icon, title: e.message, module: m.id });
      }
    } else {
      out.push({ pid: m.id, label: m.name, icon, title: m.summary, module: m.id });
    }
  }
  return { tiles: out, registry: reg };
}

export function arrange(tiles, conf = {}) {
  const order = Array.isArray(conf.order) ? conf.order : [];
  const hidden = new Set(Array.isArray(conf.hidden) ? conf.hidden : []);
  const rank = (t) => { const i = order.indexOf(t.pid); return i < 0 ? order.length + tiles.indexOf(t) : i; };
  const sorted = [...tiles].sort((a, b) => rank(a) - rank(b));
  return sorted.map((t) => ({ ...t, hidden: hidden.has(t.pid) }));
}
