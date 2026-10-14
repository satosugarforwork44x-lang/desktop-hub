// icons.js — 画面で使うアイコン（線画SVG）。色は文字色(currentColor)に従う
const svg = (body, extra = "") =>
  `<svg class="icon" ${extra} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

export const icons = {
  folder: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  folderFill: `<svg class="icon folder-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  image: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>'),
  chevron: `<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>`,
  close: svg('<path d="M6 6l12 12M18 6 6 18"/>'),
  collapse: svg('<path d="m6 15 6-6 6 6"/>'),
  expand: svg('<path d="m6 9 6 6 6-6"/>'),
  undo: svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>'),
  refresh: svg('<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>'),
  newFolder: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>'),
  upload: svg('<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>'),
  calendar: svg('<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
  link: svg('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
  check: svg('<path d="m5 12 5 5 9-10"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  dockTop: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 8.5h18" stroke-width="3"/>'),
  dockBottom: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 15.5h18" stroke-width="3"/>'),
  dockLeft: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7.5 4v16" stroke-width="3"/>'),
  dockRight: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M16.5 4v16" stroke-width="3"/>'),
  pdf: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8.5 15.5h7M8.5 12h4"/>'),
  sidebar: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>'),
  zoomIn: svg('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2M11 8v6M8 11h6"/>'),
  zoomOut: svg('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2M8 11h6"/>'),
  rotate: svg('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
  search: svg('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
  print: svg('<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>'),
  more: svg('<circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/>'),
  text: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8.5 12.5h7M8.5 15.5h7M8.5 18.5h4"/>'),
  note: svg('<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5"/><path d="M8 9h8M8 13h4"/>'),
  timer: svg('<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9.5 2h5"/>'),
  viewer: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="m8 17 2.5-3 2 2 1.5-2 2 3z"/>'),
  play: svg('<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" fill="currentColor" stroke="none"/>'),
  pause: svg('<rect x="6.5" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="13.9" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none"/>'),
  skipBack: svg('<path d="M18 6.5v11a.8.8 0 0 1-1.2.7L9 12.7a.8.8 0 0 1 0-1.4l7.8-5.5a.8.8 0 0 1 1.2.7z" fill="currentColor" stroke="none"/><path d="M6.5 6v12"/>'),
  skipFwd: svg('<path d="M6 6.5v11a.8.8 0 0 0 1.2.7l7.8-5.5a.8.8 0 0 0 0-1.4L7.2 5.8A.8.8 0 0 0 6 6.5z" fill="currentColor" stroke="none"/><path d="M17.5 6v12"/>'),
  repeat: svg('<path d="M17 2.5 20.5 6 17 9.5"/><path d="M3.5 11V9a3 3 0 0 1 3-3h14"/><path d="M7 21.5 3.5 18 7 14.5"/><path d="M20.5 13v2a3 3 0 0 1-3 3h-14"/>'),
  repeatOne: svg('<path d="M17 2.5 20.5 6 17 9.5"/><path d="M3.5 11V9a3 3 0 0 1 3-3h14"/><path d="M7 21.5 3.5 18 7 14.5"/><path d="M20.5 13v2a3 3 0 0 1-3 3h-14"/><path d="M11.2 10.2 12.5 9.5v5"/>'),
  volume: svg('<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.2 6.5a7.8 7.8 0 0 1 0 11"/>'),
  mute: svg('<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>'),
  fullscreen: svg('<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'),
  video: svg('<rect x="3" y="5.5" width="13" height="13" rx="2"/><path d="m16 10.5 5-3v9l-5-3"/>'),
  music: svg('<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>'),
  // ---- 拡張アプリ用（使わなければそのままでよい） ----
  // 写真の編集
  photoEdit: svg('<path d="M20 12.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h6.5"/><path d="m4.5 17.5 4.5-4.5 3 3 2-2 5.5 5"/><path d="m15.5 8.5 4.5-4.5 1.5 1.5-4.5 4.5-2 .5z"/>'),
  adjust: svg('<path d="M4 6.5h9M17 6.5h3M4 12h3M11 12h9M4 17.5h11M19 17.5h1"/><circle cx="15" cy="6.5" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17.5" r="2"/>'),
  crop: svg('<path d="M6.5 2.5v13a2 2 0 0 0 2 2h13"/><path d="M2.5 6.5h13a2 2 0 0 1 2 2v13"/>'),
  wand: svg('<path d="m4 20 11-11"/><path d="m14 7 3 3"/><path d="M17.5 2.5v3M16 4h3M20.5 8.5v2.5M19.25 9.75h2.5M10 3v2M9 4h2"/>'),
  layers: svg('<path d="m12 3.5 9 4.5-9 4.5L3 8z"/><path d="m3 12 9 4.5 9-4.5"/><path d="m3 16 9 4.5 9-4.5"/>'),
  // 動画の編集
  film: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 8h4M3 12h4M3 16h4M17 8h4M17 12h4M17 16h4"/>'),
  videoEdit: svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="m10.5 7.5 4 2.5-4 2.5z"/><path d="M3 19.5h18"/><path d="M8 18v3M15 18v3"/>'),
  timeline: svg('<path d="M3 5h18"/><rect x="3" y="8.5" width="9" height="4" rx="1"/><rect x="9" y="15" width="12" height="4" rx="1"/><path d="M14.5 3v18"/>'),
  scissors: svg('<circle cx="6" cy="7" r="2.6"/><circle cx="6" cy="17" r="2.6"/><path d="M8.2 8.4 20 17M8.2 15.6 20 7"/>'),
  // 3D の簡易ビューア
  cube: svg('<path d="m12 2.8 8 4.6v9.2l-8 4.6-8-4.6V7.4z"/><path d="m4 7.4 8 4.6 8-4.6M12 12v9.2"/>'),
  axes3d: svg('<path d="M12 13V3.5M12 13l8 4.5M12 13l-8 4.5"/><path d="m9.5 6 2.5-2.5L14.5 6"/><path d="m17 18.6 3-1.1-.7-3.1"/><path d="m4.7 14.4-.7 3.1 3 1.1"/>'),
  orbit3d: svg('<path d="m12 7.5 4 2.3v4.4l-4 2.3-4-2.3V9.8z"/><path d="M8 9.8l4 2.3 4-2.3M12 12.1v4.4"/><path d="M20.5 9.5A9 9 0 0 0 5 5.5"/><path d="M3.5 14.5A9 9 0 0 0 19 18.5"/><path d="m5 2.8.1 2.9 2.8-.4M19 21.2l-.1-2.9-2.8.4"/>'),
  mesh: svg('<path d="m12 3 7.8 4.5v9L12 21l-7.8-4.5v-9z"/><path d="M12 3v6.5M19.8 7.5 15 12.2M19.8 16.5 15 12.2M12 21v-6.5M4.2 16.5 9 12.2M4.2 7.5 9 12.2"/><path d="m12 9.5 3 2.7-3 2.3-3-2.3z"/>'),
  // 鍵盤（サウンドスケッチ）
  pianoKeys: svg('<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M9 13.5v6M15 13.5v6"/><rect x="7.2" y="4.5" width="3.6" height="9" rx=".9" fill="currentColor" stroke="none"/><rect x="13.2" y="4.5" width="3.6" height="9" rx=".9" fill="currentColor" stroke="none"/>'),
  // 録音（拡張「ボイスメモ」用。使わなければそのまま）
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21M8.5 21h7"/>'),
  micOff: svg('<path d="M15 9.5V6a3 3 0 0 0-5.6-1.5M9 9v2a3 3 0 0 0 4.9 2.3"/><path d="M5.5 11a6.5 6.5 0 0 0 10.8 4.9M18.5 11a6.4 6.4 0 0 1-.4 2.2"/><path d="M12 17.5V21M8.5 21h7M4 4l16 16"/>'),
  record: svg('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5" fill="currentColor" stroke="none"/>'),
  waveform: svg('<path d="M3 12h2M7 8v8M11 4v16M15 7v10M19 10v4"/>'),
  transcript: svg('<path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z"/><path d="M14 3.5V8h4"/><path d="M9 12.5h6M9 15.5h6M9 18h3.5"/>'),
  voiceMemo: svg('<rect x="3.5" y="5" width="17" height="14" rx="3"/><path d="M8 10v4M11 8.5v7M14 10.5v3M17 9.5v5"/>'),
  globe: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  gauge: svg('<path d="M4.5 18a8.5 8.5 0 1 1 15 0"/><path d="m12 13.5 4-4.5"/><circle cx="12" cy="13.5" r="1.3" fill="currentColor"/>'),
  window: svg('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 8.5h18"/>'),
  edit: svg('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>'),
  grip: svg('<circle cx="9" cy="6" r="1.2" fill="currentColor"/><circle cx="15" cy="6" r="1.2" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><circle cx="9" cy="18" r="1.2" fill="currentColor"/><circle cx="15" cy="18" r="1.2" fill="currentColor"/>'),
  eye: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'),
  eyeOff: svg('<path d="M10.6 5.6A9.8 9.8 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.7 3.4M6.3 6.9C3.9 8.6 2.5 12 2.5 12S6 18.5 12 18.5c1.6 0 3-.4 4.3-1.1"/><path d="m3 3 18 18"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
  folders: svg('<path d="M3 8a2 2 0 0 1 2-2h3.5l2 2H17a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M7 4h4l1.5 1.5H19a2 2 0 0 1 2 2V15"/>'),
  focus: svg('<circle cx="12" cy="12" r="8.5" stroke-dasharray="1.5 2.6"/><circle cx="12" cy="12" r="3.2"/>'),
  moon: svg('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
  up: svg('<path d="m6 15 6-6 6 6"/>'),
  down: svg('<path d="m6 9 6 6 6-6"/>'),
  left: svg('<path d="m15 6-6 6 6 6"/>'),
  right: svg('<path d="m9 6 6 6-6 6"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  pin: svg('<path d="M12 17v5"/><path d="M8 3h8l-1 6 3 4H6l3-4z"/>'),
  power: svg('<path d="M12 3v8"/><path d="M6.3 7.3a8 8 0 1 0 11.4 0"/>'),
  open: svg('<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>'),
  reveal: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="m13 11 2 2-2 2"/>'),
  rename: svg('<path d="M4 20h4L19 9l-4-4L4 16z"/>'),
  trash: svg('<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13M9 7V4h6v3"/>'),
  move: svg('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>'),
  tool: svg('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.1 2.1-2-2z"/>'),
};

// ファイルの種類ごとの色（拡張子 → 色）。設計業務でよく使う形式を見分けやすくする
const FILE_COLORS = {
  pdf: "#E06C5A",
  xlsx: "#4FB37A", xlsm: "#4FB37A", xls: "#4FB37A", csv: "#4FB37A",
  docx: "#5B8DEF", doc: "#5B8DEF", txt: "#8AA2B2", md: "#8AA2B2",
  pptx: "#E8894A", ppt: "#E8894A",
  png: "#B583E0", jpg: "#B583E0", jpeg: "#B583E0", tif: "#B583E0", tiff: "#B583E0",
  sldprt: "#D9B45A", sldasm: "#D9B45A", slddrw: "#D9B45A", step: "#D9B45A", stp: "#D9B45A",
  igs: "#D9B45A", iges: "#D9B45A", dxf: "#D9B45A", dwg: "#D9B45A", stl: "#D9B45A",
  msg: "#2EC4D6", eml: "#2EC4D6",
  zip: "#8AA2B2", "7z": "#8AA2B2",
};

export function fileIcon(ext) {
  const c = FILE_COLORS[ext] || "#8AA2B2";
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6 2.8h8l4.2 4.2V20a1.2 1.2 0 0 1-1.2 1.2H6A1.2 1.2 0 0 1 4.8 20V4A1.2 1.2 0 0 1 6 2.8z" fill="none" stroke="#8AA2B2" stroke-width="1.5"/>
    <path d="M14 2.8V7h4.2" fill="none" stroke="#8AA2B2" stroke-width="1.5"/>
    <rect x="7" y="12" width="10" height="5" rx="1" fill="${c}"/></svg>`;
}
