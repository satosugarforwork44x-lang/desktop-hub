// theme.js — 明るさ（dark / light / auto）と色（ACCENTS の 8 色）を <html> に付ける。
// 色の中身は hub.css の data-mode / data-accent の段にある。auto は Windows のアプリの明るさに合わせて、変わったら追従する。
import { host } from "./hub.js";

export const MODES = ["auto", "dark", "light"];
export const ACCENTS = ["aurora", "ocean", "ember", "graphite", "forest", "sakura", "gold", "indigo"];

let appearance = { mode: "dark", accent: "aurora" };
try { appearance = { ...appearance, ...((await host.config()).appearance || {}) }; } catch { /* 確認表示・起動直後 */ }

const media = matchMedia("(prefers-color-scheme: light)");
export function applyTheme(a = appearance) {
  appearance = a;
  const mode = a.mode === "auto" ? (media.matches ? "light" : "dark") : a.mode;
  document.documentElement.dataset.mode = mode === "light" ? "light" : "dark";
  document.documentElement.dataset.accent = ACCENTS.includes(a.accent) ? a.accent : "aurora";
}
media.addEventListener("change", () => { if (appearance.mode === "auto") applyTheme(); });
applyTheme();
