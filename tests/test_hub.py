"""Hubの自動テスト（標準ライブラリ unittest のみ）。

  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.app import NullBackend, PANEL_HEADER_H  # noqa: E402
from host.registry import ModuleError  # noqa: E402
from hub import build, import_sidebar  # noqa: E402


class HubTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.reg_root = t / "registries"
        (self.reg_root / "WIP" / "sub").mkdir(parents=True)
        (self.reg_root / "Projects").mkdir()
        (self.reg_root / "_to_delete").mkdir()          # "_" で始まるものはレジストリ扱いしない
        (self.reg_root / "WIP" / "a.txt").write_text("a")
        self.outside = t / "desktop"
        self.outside.mkdir()
        self.config = {
            "bar": {"dock": "top", "length": 520, "onTop": True}, "panels": {"onTop": False},
            "modulePaths": [str(ROOT / "modules")], "dataDir": str(t / "data"),
            "modules": {"folders": {"root": str(self.reg_root)}},
        }
        self.host, self.registry, self.server, self.store = build(self.config, NullBackend())
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.store.close()
        self.tmp.cleanup()

    def post(self, path, body=None, token=None):
        req = urllib.request.Request(
            f"{self.server.base_url}{path}", data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json", "X-Hub-Token": token if token is not None else self.server.token},
            method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def call(self, fn, **args):
        return self.registry.call("folders", fn, args)


class TestRegistryAndServer(HubTestBase):
    def test_modules_loaded_without_errors(self):
        self.assertEqual(set(self.registry.modules), {"folders", "pdf", "calendar", "settings", "notes", "timer", "media", "web", "system"})
        self.assertEqual(self.registry.errors, [])
        for m in self.registry.modules.values():
            self.assertEqual(m.errors, [], m.id)

    def test_token_required(self):
        code, body = self.post("/api/registry", token="wrong")
        self.assertEqual(code, 403)
        code, body = self.post("/api/registry")
        self.assertTrue(body["ok"])

    def test_only_exported_functions_callable(self):
        _, body = self.post("/api/call", {"module": "folders", "fn": "_move", "args": {}})
        self.assertFalse(body["ok"])
        self.assertIn("公開されていない", body["error"])

    def test_module_error_is_user_facing(self):
        _, body = self.post("/api/call", {"module": "folders", "fn": "list_dir", "args": {"registry": "nope"}})
        self.assertFalse(body["ok"])
        self.assertIn("見つからない", body["error"])

    def test_static_serving_is_confined(self):
        with urllib.request.urlopen(f"{self.server.base_url}/ui/bar.html") as r:
            self.assertEqual(r.status, 200)
        with urllib.request.urlopen(f"{self.server.base_url}/m/folders/ui/panel.js") as r:
            self.assertIn("text/javascript", r.headers["Content-Type"])
        for bad in ["/ui/../hub.py", "/m/folders/api.py", "/m/folders/ui/../api.py", "/m/nope/ui/x.js"]:
            with self.assertRaises(urllib.error.HTTPError, msg=bad):
                urllib.request.urlopen(f"{self.server.base_url}{bad}")


class TestFolders(HubTestBase):
    def test_instances_skip_underscore(self):
        self.assertEqual([i["id"] for i in self.call("instances")], ["Projects", "WIP"])

    def test_list_dir_dirs_first(self):
        items = self.call("list_dir", registry="WIP")["items"]
        self.assertEqual([i["name"] for i in items], ["sub", "a.txt"])

    def test_move_in_unique_name_and_undo(self):
        f = self.outside / "a.txt"
        f.write_text("outside")
        r = self.call("move_in", registry="WIP", paths=[str(f)])
        self.assertEqual(r["moved"], ["a (2).txt"])               # 上書きしない
        self.assertFalse(f.exists())
        self.assertEqual((self.reg_root / "WIP" / "a.txt").read_text(), "a")
        self.call("undo", registry="WIP")
        self.assertEqual(f.read_text(), "outside")                # 元の場所に戻る

    def test_drop_on_file_row_goes_to_its_folder(self):
        (self.reg_root / "WIP" / "sub" / "x.txt").write_text("x")
        f = self.outside / "new.txt"
        f.write_text("n")
        self.call("move_in", registry="WIP", paths=[str(f)], dest_rel="sub/x.txt")
        self.assertTrue((self.reg_root / "WIP" / "sub" / "new.txt").exists())

    def test_move_dir_into_itself_rejected(self):
        r = self.call("move_within", registry="WIP", rels=["sub"], dest_rel="sub")
        self.assertTrue(r["errors"])
        self.assertTrue((self.reg_root / "WIP" / "sub").is_dir())

    def test_path_traversal_rejected(self):
        with self.assertRaises(ModuleError):
            self.call("list_dir", registry="WIP", rel="../Projects")
        with self.assertRaises(ModuleError):
            self.call("list_dir", registry="../registries")

    def test_move_to_other_registry_and_rename(self):
        self.call("move_to", registry="WIP", rels=["a.txt"], target="Projects")
        self.assertTrue((self.reg_root / "Projects" / "a.txt").exists())
        self.call("rename", registry="Projects", rel="a.txt", new_name="b.txt")
        self.assertTrue((self.reg_root / "Projects" / "b.txt").exists())

    def test_trash(self):
        r = self.call("trash", registry="WIP", rels=["a.txt"])
        self.assertEqual(r["trashed"], ["a.txt"])
        self.assertFalse((self.reg_root / "WIP" / "a.txt").exists())

    def test_create_registry_validation(self):
        self.call("create_registry", name="New")
        self.assertTrue((self.reg_root / "New").is_dir())
        for bad in ["", "a/b", "_x", "WIP"]:
            with self.assertRaises(ModuleError, msg=bad):
                self.call("create_registry", name=bad)


class TestWindows(HubTestBase):
    def test_panel_open_close_collapse_persist(self):
        r = self.host.open_panel("folders:WIP")
        self.assertIn("panel.html?id=folders:WIP", r["url"])
        self.assertIn(self.server.token, r["url"])
        self.host.collapse_panel("folders:WIP", True)
        self.assertEqual(self.host.backend.windows["folders:WIP"]["geom"][3], PANEL_HEADER_H)
        self.host.collapse_panel("folders:WIP", False)
        self.assertEqual(self.host.backend.windows["folders:WIP"]["geom"][3], 420)  # manifestの高さに戻る
        self.host.close_panel("folders:WIP")
        self.assertFalse(self.store.get("window", "folders:WIP")["open"])

    def test_restore_reopens_previously_open(self):
        self.host.open_panel("pdf")
        self.host.backend.windows.clear()                      # 終了を模擬（openフラグは残る）
        self.host.restore_panels()
        self.assertIn("pdf", self.host.backend.windows)

    def test_unknown_module_panel_rejected(self):
        with self.assertRaises(ModuleError):
            self.host.open_panel("nope")

    def test_bar_expand_geometry(self):
        self.host.create_bar()
        self.assertEqual(self.host.backend.windows["bar"]["geom"], [700, 0, 520, 6])
        self.host.bar_set(expanded=True)
        self.assertEqual(self.host.backend.windows["bar"]["geom"][3], 52)
        self.host.bar_set(pinned=True)
        self.host.bar_set(expanded=False)                      # ピン留め中は畳まない
        self.assertEqual(self.host.backend.windows["bar"]["geom"][3], 52)

    def test_import_sidebar(self):
        sj = Path(self.tmp.name) / "sidebar_data.json"
        sj.write_text(json.dumps({"registries": {"WIP": {"geometry": [180, 205, 299, 304], "auto_open": True}}}))
        db = Path(self.tmp.name) / "imp.db"
        self.assertEqual(import_sidebar(db, sj), 1)


class TestPdfTools(HubTestBase):
    def setUp(self):
        super().setUp()
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            self.skipTest("pymupdf がない")
        import pymupdf
        doc = pymupdf.open()
        for i in range(3):
            doc.new_page().insert_text((72, 72), f"page {i + 1}")
        self.pdf = self.outside / "sample.pdf"
        doc.save(self.pdf)

    def run_action(self, **params):
        return self.registry.run_action("pdf", "to_images", str(self.pdf), params)

    def test_png_pages(self):
        r = self.run_action(format="png", dpi=100, pages="1,3")
        self.assertTrue(r["ok"], r["stderr"])
        self.assertEqual([Path(p).name for p in r["result"]["outputs"]], ["sample_p001.png", "sample_p003.png"])

    def test_jpeg_works(self):  # 旧版は format="JPG" で必ず失敗していた
        r = self.run_action(format="jpeg", dpi=72)
        self.assertTrue(r["ok"], r["stderr"])
        self.assertEqual(len(r["result"]["outputs"]), 3)

    def test_tiff_multipage_bw(self):
        from PIL import Image
        r = self.run_action(format="tiff", dpi=150, tiff_mode="bw")
        self.assertTrue(r["ok"], r["stderr"])
        with Image.open(r["result"]["outputs"][0]) as im:
            self.assertEqual((im.n_frames, im.info.get("compression")), (3, "group4"))

    # ---------- ビューア・テキスト化・Claude ----------
    def test_open_doc_and_blob_needs_token(self):
        r = self.registry.call("pdf", "open_doc", {"path": str(self.pdf)})
        self.assertEqual(r["panel"], f"pdf:{r['key']}")
        url = f"{self.server.base_url}/blob/pdf/{r['key']}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"X-Hub-Token": self.server.token})) as res:
            self.assertEqual(res.headers["Content-Type"], "application/pdf")
            self.assertEqual(res.read()[:4], b"%PDF")
        for bad in (url, f"{self.server.base_url}/blob/pdf/unknownkey?t={self.server.token}"):
            with self.assertRaises(urllib.error.HTTPError):   # 合言葉なし・開いていない PDF は渡さない
                urllib.request.urlopen(bad)

    def test_open_file_routes_to_viewer(self):
        r = self.host.open_file(str(self.pdf))
        pid = [w for w in self.host.backend.windows if w.startswith("pdf:")][0]
        self.assertEqual(self.host.backend.windows[pid]["geom"][2:], [880, 1000])   # ビューアは大きめの窓
        self.assertTrue(r["open"])
        with self.assertRaises(ModuleError):
            self.host.open_file(str(self.outside / "missing.pdf"))

    def test_extract_text_saves_txt(self):
        key = self.registry.call("pdf", "open_doc", {"path": str(self.pdf)})["key"]
        r = self.registry.call("pdf", "extract_text", {"key": key, "ocr": "off"})
        txt = Path(r["path"]).read_text(encoding="utf-8")
        self.assertIn("--- p.2 ---\npage 2", txt)
        self.assertEqual(r["name"], "sample.txt")
        self.assertEqual(self.registry.call("pdf", "extract_text", {"key": key, "ocr": "off"})["name"], "sample (2).txt")

    def test_folders_read_text_reads_pdf(self):
        import shutil
        shutil.copy(self.pdf, self.reg_root / "WIP" / "doc.pdf")
        r = self.registry.call("folders", "read_text", {"registry": "WIP", "rel": "doc.pdf"})
        self.assertEqual(r["pages"], 3)
        self.assertIn("page 3", r["text"])
        self.assertNotIn("scannedPages", r)

    def test_second_launch_hands_off(self):
        from hub import _ask_running
        cfg = dict(self.config)
        self.assertFalse(_ask_running(cfg, "config", {}))            # 連絡先が無い → 自分で起動する
        from hub import _run_file
        f = _run_file(cfg)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"port": self.server.port, "token": self.server.token}), encoding="utf-8")
        self.assertTrue(_ask_running(cfg, "open_file", {"path": str(self.pdf)}))   # 起動中の Hub が開く
        self.assertTrue(any(w.startswith("pdf:") for w in self.host.backend.windows))

    def test_bad_pages_reports_error(self):
        r = self.run_action(pages="9")
        self.assertFalse(r["ok"])
        self.assertIn("範囲外", r["stderr"])

    def test_param_validation(self):
        with self.assertRaises(ModuleError):
            self.run_action(dpi=5000)
        with self.assertRaises(ModuleError):
            self.run_action(format="bmp")
        with self.assertRaises(ModuleError):
            self.registry.run_action("pdf", "to_images", str(self.outside / "x.txt"), {})


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:once
DTSTART:20261012T050000Z
DTEND:20261012T060000Z
SUMMARY:Design review
LOCATION:Room A
END:VEVENT
BEGIN:VEVENT
UID:daily
DTSTART;TZID=Asia/Tokyo:20261010T090000
DTEND;TZID=Asia/Tokyo:20261010T091500
RRULE:FREQ=DAILY;UNTIL=20261020T000000Z
EXDATE;TZID=Asia/Tokyo:20261013T090000
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:daily
RECURRENCE-ID;TZID=Asia/Tokyo:20261014T090000
DTSTART;TZID=Asia/Tokyo:20261014T100000
DTEND;TZID=Asia/Tokyo:20261014T101500
SUMMARY:Standup (moved)
END:VEVENT
BEGIN:VEVENT
UID:holiday
DTSTART;VALUE=DATE:20261012
DTEND;VALUE=DATE:20261013
SUMMARY:Holiday
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTART:20261011T010000Z
DTEND:20261011T020000Z
STATUS:CANCELLED
SUMMARY:Gone
END:VEVENT
END:VCALENDAR
"""


class CalendarTest(HubTestBase):
    """calendar: iCal の読み込み（繰り返し・除外日・個別変更・終日・取り消し）とバー用の status。"""

    def setUp(self):
        super().setUp()
        import os
        import time as _t
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Tokyo"   # 期待値を固定するため、ローカル時刻を日本時間にする
        _t.tzset()
        self.api = self.registry.get("calendar").api

    def tearDown(self):
        import os
        import time as _t
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        _t.tzset()
        super().tearDown()

    def test_parse_recurring_and_overrides(self):
        from datetime import datetime
        evs = self.api.parse_ics(ICS, now=datetime(2026, 10, 10, 8, 0), days=7)
        titles = [(e["start"], e["title"]) for e in evs]
        self.assertIn(("2026-10-12T14:00", "Design review"), titles)          # UTC → 日本時間
        self.assertIn(("2026-10-12T00:00", "Holiday"), titles)
        self.assertTrue(next(e for e in evs if e["title"] == "Holiday")["allDay"])
        standups = [s for s, t in titles if t == "Standup"]
        self.assertIn("2026-10-10T09:00", standups)
        self.assertNotIn("2026-10-13T09:00", standups)                         # EXDATE で除外
        self.assertNotIn("2026-10-14T09:00", standups)                         # 個別変更で置き換え
        self.assertIn(("2026-10-14T10:00", "Standup (moved)"), titles)
        self.assertNotIn("Gone", [t for _, t in titles])                       # 取り消し済み

    def test_status_and_urls(self):
        f = Path(self.tmp.name) / "cal.ics"
        f.write_bytes(ICS)
        self.assertFalse(self.registry.call("calendar", "upcoming", {})["configured"])
        with self.assertRaises(ModuleError):
            self.registry.call("calendar", "set_urls", {"urls": ["ftp://x"]})
        self.registry.call("calendar", "set_urls", {"urls": [str(f)]})
        st = self.registry.call("calendar", "status", {})
        # テスト用の予定は 2026-10 のものなので、実行日によっては None（予定が過ぎている）になる
        if st is not None:
            self.assertEqual((st["prefix"], st["icon"]), ("next", "calendar"))


class SettingsAndBarTest(HubTestBase):
    """設定画面からの保存と、バーの上下左右の配置。"""

    def setUp(self):
        super().setUp()
        self.cfg_file = Path(self.tmp.name) / "hub.config.json"
        self.cfg_file.write_text(json.dumps({"bar": {"length": 600}, "custom": 1}), encoding="utf-8")
        self.host.config_path = self.cfg_file

    def test_save_keeps_other_keys_and_validates(self):
        r = self.host.settings_set({"lang": "en", "bar.dock": "left", "mcp.panels": {"WIP": "write", "Projects": "hidden"}})
        saved = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["custom"], 1)                       # 手で書いた項目は残る
        self.assertEqual(saved["bar"], {"length": 600, "dock": "left"})
        self.assertEqual((r["settings"]["lang"], r["settings"]["dock"], r["settings"]["mcpPanels"]), ("en", "left", {"WIP": "write"}))
        self.assertEqual(saved["mcp"], {"panels": {"WIP": "write"}})          # hidden は書かない
        self.assertEqual(set(r["settings"]["panels"]), {"WIP", "Projects"})
        self.assertFalse(r["restart"])
        self.assertTrue(self.host.settings_set({"modules.folders.root": str(self.reg_root / "x")})["restart"])
        for bad in ({"bar.dock": "middle"}, {"dataDir": "C:/"}, {"mcp.calendar": "yes"}, {"mcp.panels": {"WIP": "all"}}):
            with self.assertRaises(ModuleError):
                self.host.settings_set(bad)

    def test_shortcut_settings_outside_windows(self):
        import os
        st = self.host.settings_get()["shortcuts"]
        self.assertEqual(set(st), {"startup", "startmenu", "desktop"})
        if os.name != "nt":
            self.assertFalse(any(st.values()))
            with self.assertRaises(ModuleError):
                self.host.set_shortcut("startmenu", True)
            self.assertEqual(self.host.repair_shortcuts(), [])

    def test_bar_grows_to_fit_its_tiles(self):
        self.host.config["bar"]["length"] = "auto"
        self.host.create_bar()
        self.host.bar_set(expanded=True, length=1100)                  # 画面側が測った長さ
        self.assertEqual(self.host.backend.windows["bar"]["geom"], [410, 0, 1100, 52])   # 中央に置いたまま伸びる
        self.host.bar_set(length=5000)
        self.assertEqual(self.host.backend.windows["bar"]["geom"][2], 1880)                # 画面の幅で止まる
        self.host.config["bar"]["length"] = 520
        self.host.bar_set(length=900)                                   # 長さを固定しているときは変えない
        self.assertEqual(self.host.backend.windows["bar"]["geom"][2], 1880)

    def test_folder_display_mode(self):
        self.host.create_bar()
        r = self.host.settings_set({"bar.folders": "group"})
        self.assertEqual(r["settings"]["barFolders"], "group")
        self.assertEqual(self.host.backend.windows["bar"].get("reloads"), 1)   # バーを読み込み直して反映
        with self.assertRaises(ModuleError):
            self.host.settings_set({"bar.folders": "tree"})
        self.assertEqual(self.host.open_panel("folders")["open"], True)        # 「フォルダ」タイル = 一覧の窓

    def test_bar_tiles_order_and_hidden(self):
        self.host.create_bar()
        r = self.host.settings_set({"bar.tiles": {"order": ["web", "folders:WIP", "web"], "hidden": ["notes"]}})
        self.assertEqual(r["settings"]["barTiles"], {"order": ["web", "folders:WIP"], "hidden": ["notes"]})
        self.assertEqual(self.host.backend.windows["bar"].get("reloads"), 1)   # バーだけ読み込み直す
        for bad in ({"order": "web"}, {"hidden": [1]}):
            with self.assertRaises(ModuleError):
                self.host.settings_set({"bar.tiles": bad})

    def test_bar_geometry_on_all_edges(self):
        # NullBackend の作業領域は 1920x1080、拡大率 1.0。長さは config の 520
        expect = {
            "top": ([700, 0, 520, 6], [700, 0, 520, 52]),
            "bottom": ([700, 1074, 520, 6], [700, 1028, 520, 52]),
            "left": ([0, 280, 6, 520], [0, 280, 64, 520]),
            "right": ([1914, 280, 6, 520], [1856, 280, 64, 520]),
        }
        for dock, (collapsed, expanded) in expect.items():
            self.host.config["bar"]["dock"] = dock
            self.assertEqual(self.host._bar_geom(False), collapsed, dock)
            self.assertEqual(self.host._bar_geom(True), expanded, dock)

    def test_recreate_bar_does_not_quit(self):
        self.host.create_bar()
        self.host.settings_set({"bar.dock": "right"})
        self.assertTrue(self.host.backend.exists("bar"))
        self.assertIn("dock=right", self.host.backend.windows["bar"]["url"])
        self.assertFalse(self.host._quitting)


class FoldersDefaultsTest(HubTestBase):
    def test_empty_root_gets_inbox_and_search(self):
        from host.config import DEFAULTS
        self.assertEqual(DEFAULTS["modules"]["folders"]["root"], "~/Hub")
        empty = Path(self.tmp.name) / "fresh"
        mod = self.registry.get("folders")
        mod.ctx.config = {"root": str(empty)}
        mod.api.setup(mod.ctx)
        self.assertTrue((empty / "Inbox").is_dir())
        mod.ctx.config = {"root": str(self.reg_root)}
        hits = self.registry.call("folders", "search", {"query": "A.TXT"})
        self.assertEqual(hits, [{"registry": "WIP", "rel": "a.txt", "dir": False}])


class McpTest(HubTestBase):
    """hub_mcp.py: Claude に見せる道具の範囲（既定は読み取りだけ）と、実際の呼び出し。"""

    def setUp(self):
        super().setUp()
        try:
            import hub_mcp  # noqa: F401
        except ImportError:
            self.skipTest("mcp が入っていない")

    def _server(self, panels: dict, calendar: bool = True):
        import copy
        import hub_mcp
        cfg = copy.deepcopy(self.config)
        cfg["dataDir"] = str(Path(self.tmp.name) / "data_mcp")
        cfg["mcp"] = {"panels": panels, "calendar": calendar}
        return hub_mcp.create_server(cfg)[0]

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def _call(self, srv, name, args):
        """(結果, エラーだったか)。エラーは MCP の版により例外か is_error で返るので両方を見る。"""
        try:
            r = self._run(srv.call_tool(name, args))
        except Exception as e:  # noqa: BLE001
            self.assertNotIn("UnexpectedToolError", type(e).__name__, f"想定外の失敗: {e!r} / {e.__cause__!r}")
            return e, True
        return r, bool(getattr(r, "is_error", getattr(r, "isError", False)))

    def test_web_shortcuts_list_only(self):
        srv = self._server({})
        import hub_mcp  # noqa: F401
        self.registry.call("web", "save", {"url": "https://news.example.com", "name": "News"})
        cfg_dir = Path(self.tmp.name) / "data_mcp"
        # MCP 側は別の保存場所を使うので、同じ保存場所を指す設定で作り直す
        import copy
        import hub_mcp as hm
        cfg = copy.deepcopy(self.config)
        cfg["mcp"] = {"panels": {}, "web": True}
        r, err = self._call(hm.create_server(cfg)[0], "web_shortcuts", {})
        self.assertFalse(err)
        self.assertIn("news.example.com", str(r))
        cfg["mcp"]["web"] = False
        _, err = self._call(hm.create_server(cfg)[0], "web_shortcuts", {})
        self.assertTrue(err)
        del srv, cfg_dir

    def test_nothing_shared_by_default(self):
        srv = self._server({}, calendar=False)
        names = {t.name for t in self._run(srv.list_tools())}
        self.assertFalse(any("trash" in n or "delete" in n for n in names))   # 削除は Claude に渡さない
        _, err = self._call(srv, "folders_list", {"panel": "WIP"})
        self.assertTrue(err)                                       # 見せていないフォルダ窓は読めない
        _, err = self._call(srv, "calendar_upcoming", {})
        self.assertTrue(err)                                       # 予定も見せていない
        _, err = self._call(srv, "folders_write_text", {"panel": "WIP", "path": "x.md", "content": "x"})
        self.assertTrue(err)

    def test_read_panel_is_read_only(self):
        srv = self._server({"WIP": "read"})
        r, err = self._call(srv, "folders_read_text", {"panel": "WIP", "path": "a.txt"})
        self.assertFalse(err)
        _, err = self._call(srv, "folders_write_text", {"panel": "WIP", "path": "x.md", "content": "x"})
        self.assertTrue(err)                                       # 「読む」には書けない
        r, err = self._call(srv, "folders_read_text", {"panel": "WIP", "path": "a.txt"})
        self.assertFalse(err)
        hits, _ = self._call(srv, "folders_search", {"query": "a"})
        self.assertNotIn("Projects", str(getattr(hits, "content", hits)))           # 見せていない Projects は検索にも出ない

    def test_write_panel_saves_deliverables_and_moves(self):
        srv = self._server({"WIP": "write", "Projects": "write"})
        _, err = self._call(srv, "folders_write_text", {"panel": "WIP", "path": "out/report.md", "content": "# 報告"})
        self.assertFalse(err)
        self.assertEqual((self.reg_root / "WIP" / "out" / "report.md").read_text(encoding="utf-8"), "# 報告")
        self._call(srv, "folders_write_text", {"panel": "WIP", "path": "out/report.md", "content": "v2"})
        self.assertTrue((self.reg_root / "WIP" / "out" / "report (2).md").exists())   # 既定は上書きしない
        _, err = self._call(srv, "folders_write_text", {"panel": "WIP", "path": "x.exe", "content": "MZ"})
        self.assertTrue(err)                                       # テキスト以外は書けない
        _, err = self._call(srv, "folders_write_text", {"panel": "WIP", "path": "../escape.md", "content": "x"})
        self.assertTrue(err)                                       # フォルダ窓の外には書けない
        self._call(srv, "folders_move", {"panel": "WIP", "paths": ["a.txt"], "to_panel": "Projects"})
        self.assertTrue((self.reg_root / "Projects" / "a.txt").exists())
        self._call(srv, "folders_undo", {"panel": "WIP"})
        self.assertTrue((self.reg_root / "WIP" / "a.txt").exists())

    def test_settings_change_applies_without_restart(self):
        import copy
        import hub_mcp
        cfg = copy.deepcopy(self.config)
        cfg["dataDir"] = str(Path(self.tmp.name) / "data_mcp")
        live = {"mcp": {"panels": {}}}
        srv = hub_mcp.create_server(cfg, reload=lambda: live)[0]
        _, err = self._call(srv, "folders_list", {"panel": "WIP"})
        self.assertTrue(err)
        live["mcp"]["panels"] = {"WIP": "read"}                    # 設定画面で「読む」にした
        _, err = self._call(srv, "folders_list", {"panel": "WIP"})
        self.assertFalse(err)                                      # Claude Desktop を再起動しなくても効く

    def test_cannot_move_into_read_panel(self):
        srv = self._server({"WIP": "write", "Projects": "read"})
        _, err = self._call(srv, "folders_move", {"panel": "WIP", "paths": ["a.txt"], "to_panel": "Projects"})
        self.assertTrue(err)
        self.assertTrue((self.reg_root / "WIP" / "a.txt").exists())

class UpgradeTest(unittest.TestCase):
    """アップデートに備えた仕組み: 設定の移し替え・古い置き場所からの引っ越し・モジュールの版チェック。"""

    def test_migrate_config_v1(self):
        from host.config import CONFIG_VERSION, migrate_config
        old = {"mcp": {"write": True, "calendar": False}, "dataDir": "data", "modulePaths": ["modules"], "lang": "en"}
        new, changed = migrate_config(old)
        self.assertTrue(changed)
        self.assertEqual(new, {"mcp": {"calendar": False}, "lang": "en", "configVersion": CONFIG_VERSION})
        self.assertEqual(migrate_config(new), (new, False))          # 2回目は何もしない

    def test_legacy_files_move_out_of_app_folder(self):
        import os
        import host.config as cfgmod
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            app, home = t / "app", t / "home"
            (app / "data").mkdir(parents=True)
            (app / "data" / "hub.db").write_text("db")
            (app / "hub.config.json").write_text('{"lang": "ja"}', encoding="utf-8")
            saved = (cfgmod.APP_ROOT, cfgmod.LEGACY_CONFIG, cfgmod.USER_CONFIG, os.environ.get("HUB_HOME"))
            try:
                os.environ["HUB_HOME"] = str(home)
                cfgmod.APP_ROOT, cfgmod.LEGACY_CONFIG, cfgmod.USER_CONFIG = app, app / "hub.config.json", home / "hub.config.json"
                done = cfgmod.migrate_legacy_files()
                self.assertEqual(len(done), 2)
                self.assertEqual(json.loads((home / "hub.config.json").read_text(encoding="utf-8")), {"lang": "ja"})
                self.assertTrue((home / "data" / "hub.db").exists())
                self.assertTrue((app / "hub.config.json.migrated").exists())   # 元は名前を変えて残す
                self.assertEqual(cfgmod.migrate_legacy_files(), [])            # 2回目は何もしない
            finally:
                cfgmod.APP_ROOT, cfgmod.LEGACY_CONFIG, cfgmod.USER_CONFIG = saved[:3]
                if saved[3] is None:
                    os.environ.pop("HUB_HOME", None)
                else:
                    os.environ["HUB_HOME"] = saved[3]

    def test_module_requires(self):
        from host.registry import incompatible
        from host.version import MODULE_API, VERSION
        self.assertIsNone(incompatible({}))
        self.assertIsNone(incompatible({"hub": f">={VERSION}", "moduleApi": MODULE_API}))
        self.assertIn("動かない", incompatible({"hub": ">=99.0"}))
        self.assertIn("約束", incompatible({"moduleApi": MODULE_API + 1}))
        self.assertIn("読めない", incompatible({"hub": "latest"}))


class IntroTest(HubTestBase):
    def test_bar_starts_expanded_with_intro(self):
        self.host.create_bar(intro=True)
        self.assertIn("intro=1", self.host.backend.windows["bar"]["url"])
        self.assertEqual(self.host.backend.windows["bar"]["geom"][3], 6)    # 細い線から始める（画面側が広げる）
        self.host.config["bar"]["intro"] = False
        self.host.recreate_bar()
        self.assertIn("intro=0", self.host.backend.windows["bar"]["url"])
        self.assertEqual(self.host.backend.windows["bar"]["geom"][3], 6)


class RestoreTest(HubTestBase):
    """次回の起動に引き継ぐもの: パネルの位置・大きさ・開閉、バーの 📌。画面外に残った窓は戻す。"""

    def test_pin_survives_restart(self):
        self.host.bar_set(pinned=True)
        from host.app import Host
        again = Host(self.config, self.store, NullBackend(), lambda: "")
        self.assertTrue(again.bar_set()["pinned"])

    def test_pinned_bar_goes_behind_windows(self):
        self.host.create_bar()
        self.host.bar_set(pinned=True)
        self.assertEqual(self.host.backend.windows["bar"]["z"], "bottom")   # 他の窓の後ろ
        self.host.bar_set(pinned=False)
        self.assertEqual(self.host.backend.windows["bar"]["z"], "top")      # 細い線は手前（触れるように）

    def test_panels_reopen_where_they_were(self):
        self.host.open_panel("folders:WIP")
        self.host._update_geom("folders:WIP", x=300, y=200, w=400, h=500)
        import time
        time.sleep(0.6)  # 保存は少し遅れて行う（ドラッグ中に何度も書かないため）
        self.host.backend.destroy("folders:WIP")             # 終了したのと同じ（open は True のまま）
        self.host.restore_panels()
        self.assertEqual(self.host.backend.windows["folders:WIP"]["geom"], [300, 200, 400, 500])

    def test_offscreen_panel_is_brought_back(self):
        self.store.set("window", "folders:WIP", {"x": 4000, "y": 300, "w": 340, "h": 480, "open": True})
        st = self.host.panel_state("folders:WIP")
        self.assertLess(st["x"], 1920)                        # 外したモニターの位置からは戻す


class NotesTest(HubTestBase):
    def c(self, fn, **kw):
        return self.registry.call("notes", fn, kw)

    def test_add_todo_done_undo(self):
        a = self.c("add", text="牛乳を買う", todo=True)
        self.c("add", text="ただのメモ")
        self.assertEqual(len(self.c("items")), 2)
        self.c("update", id=a["id"], done=True)
        self.assertEqual(self.c("clear_done")["removed"], 1)
        self.assertEqual(len(self.c("items")), 1)
        self.c("restore")                                    # 元に戻せる
        self.assertEqual(len(self.c("items")), 2)
        b = self.c("update", id=a["id"], todo=False)          # メモに戻すと完了も外れる
        self.assertFalse(b["done"])

    def test_empty_rejected(self):
        _, body = self.post("/api/call", {"module": "notes", "fn": "add", "args": {"text": "  "}})
        self.assertFalse(body["ok"])

    def test_image_paste_and_blob(self):
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        it = self.c("add_image", data_url="data:image/png;base64," + base64.b64encode(png).decode())
        url = f"{self.server.base_url}/blob/notes/{it['image']}?t={self.server.token}"
        with urllib.request.urlopen(url) as r:
            self.assertEqual(r.read(), png)
        with self.assertRaises(urllib.error.HTTPError):       # 保存場所の外は渡さない
            urllib.request.urlopen(f"{self.server.base_url}/blob/notes/..%2F..%2Fhub.db?t={self.server.token}")
        _, body = self.post("/api/call", {"module": "notes", "fn": "add_image", "args": {"data_url": "data:text/html;base64,PGI+"}})
        self.assertFalse(body["ok"])


class TimerTest(HubTestBase):
    def c(self, fn, **kw):
        return self.registry.call("timer", fn, kw)

    def test_start_pause_resume_reset(self):
        self.assertIsNone(self.c("status"))
        s = self.c("start", minutes=25, label="集中")
        self.assertFalse(s["paused"])
        st = self.c("status")
        self.assertTrue(st["countdown"])
        self.assertEqual(st["prefix"], "集中")
        p = self.c("pause")
        self.assertTrue(p["paused"])
        self.assertAlmostEqual(p["remain"], 1500, delta=2)
        self.assertTrue(self.c("resume")["end"])
        self.c("reset")
        self.assertIsNone(self.c("state"))

    def test_done_then_cleared(self):
        import time
        self.c("start", minutes=1)
        st = self.store.get("timer.timer", "state")
        self.store.set("timer.timer", "state", {**st, "end": time.time() - 5})
        self.assertTrue(self.c("status")["done"])              # 終わった直後は「終了」を出す
        self.store.set("timer.timer", "state", {**st, "end": time.time() - 3600})
        self.assertIsNone(self.c("status"))                    # しばらくしたら消える

    def test_bad_minutes(self):
        for v in (0, -1, "abc", 99999):
            _, body = self.post("/api/call", {"module": "timer", "fn": "start", "args": {"minutes": v}})
            self.assertFalse(body["ok"])


class ViewerImageTest(HubTestBase):
    """ビューア（モジュール id は pdf）で画像を開く。TIFF は PNG にして渡す。"""

    def setUp(self):
        super().setUp()
        from PIL import Image
        self.dir = Path(self.tmp.name) / "photos"
        self.dir.mkdir()
        for n in ("a.png", "b.jpg", "c.webp"):
            Image.new("RGB", (40, 30), (200, 80, 40)).save(self.dir / n)
        pages = [Image.new("L", (50, 70), 255), Image.new("L", (50, 70), 0)]
        pages[0].save(self.dir / "scan.tif", save_all=True, append_images=pages[1:])

    def c(self, fn, **kw):
        return self.registry.call("pdf", fn, kw)

    def test_open_image_and_neighbors(self):
        r = self.c("open_doc", path=str(self.dir / "a.png"))
        self.assertEqual(r["kind"], "image")
        info = self.c("doc_info", key=r["key"])
        self.assertEqual((info["width"], info["height"]), (40, 30))
        n = self.c("neighbor", key=r["key"], step=1)
        self.assertEqual((n["name"], n["index"], n["count"]), ("b.jpg", 2, 4))
        back = self.c("neighbor", key=r["key"], step=-1)          # 先頭の前は最後へ回る
        self.assertEqual(back["name"], "scan.tif")

    def test_tiff_pages_served_as_png(self):
        r = self.c("open_doc", path=str(self.dir / "scan.tif"))
        self.assertEqual(self.c("doc_info", key=r["key"])["pages"], 2)
        with urllib.request.urlopen(f"{self.server.base_url}/blob/pdf/{r['key']}/2?t={self.server.token}") as res:
            self.assertEqual(res.headers["Content-Type"], "image/png")
            self.assertTrue(res.read().startswith(b"\x89PNG"))

    def test_open_with_routes_images_to_viewer(self):
        self.host.open_file(str(self.dir / "b.jpg"))
        self.assertTrue(any(w.startswith("pdf:") for w in self.host.backend.windows))

    def test_other_files_rejected(self):
        (self.dir / "x.exe").write_bytes(b"MZ")                    # txt は 0.11 から読める。実行ファイルは開かない
        _, body = self.post("/api/call", {"module": "pdf", "fn": "open_doc", "args": {"path": str(self.dir / "x.exe")}})
        self.assertFalse(body["ok"])


class MediaTest(HubTestBase):
    def setUp(self):
        super().setUp()
        self.dir = Path(self.tmp.name) / "music"
        self.dir.mkdir()
        (self.dir / "b song.mp3").write_bytes(b"ID3" + bytes(range(256)) * 40)
        (self.dir / "a clip.mp4").write_bytes(b"\0" * 5000)
        (self.dir / "old.avi").write_bytes(b"RIFF")
        (self.dir / "note.txt").write_text("x")

    def c(self, fn, **kw):
        return self.registry.call("media", fn, kw)

    def test_add_folder_and_range(self):
        st = self.c("add", paths=[str(self.dir)])
        self.assertEqual([i["name"] for i in st["items"]], ["a clip", "b song", "old"])   # 名前順・音楽と動画以外は入れない
        self.assertEqual({i["name"]: i["native"] for i in st["items"]}["old"], False)       # AVI は変換が必要
        song = next(i for i in st["items"] if i["ext"] == "mp3")
        req = urllib.request.Request(f"{self.server.base_url}/blob/media/{song['key']}?t={self.server.token}",
                                     headers={"Range": "bytes=3-12"})
        with urllib.request.urlopen(req) as r:                       # 動画・音楽のシークに必要な「途中から」
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers["Content-Range"], f"bytes 3-12/{3 + 256 * 40}")
            self.assertEqual(r.read(), bytes(range(10)))

    def test_open_with_plays_in_media_panel(self):
        self.host.open_file(str(self.dir / "b song.mp3"))
        self.assertIn("media", self.host.backend.windows)
        st = self.c("state")
        self.assertEqual(next(i for i in st["items"] if i["key"] == st["current"])["name"], "b song")

    def test_not_in_playlist_not_served(self):
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.server.base_url}/blob/media/abcdef123456?t={self.server.token}")


class WebShortcutTest(HubTestBase):
    def c(self, fn, **kw):
        return self.registry.call("web", fn, kw)

    def test_save_and_launch_mini(self):
        it = self.c("save", url="news.example.com", name="", open="mini")
        self.assertEqual((it["url"], it["name"]), ("https://news.example.com", "news.example.com"))
        r = self.c("launch", id=it["id"])
        self.assertEqual(r["url"], "https://news.example.com")
        self.host.open_web(it["id"], r["url"], r["name"])
        self.assertTrue(self.host.backend.windows[f"web:{it['id']}"]["web"])
        self.host.restore_panels()                                   # ミニ窓はパネルとして復元しない
        self.assertNotIn(f"web:{it['id']}", [k for k in self.store.items("window")])

    def test_only_http_urls(self):
        for bad in ("javascript:alert(1)", "file:///C:/Windows", "ftp://x"):
            _, body = self.post("/api/call", {"module": "web", "fn": "save", "args": {"url": bad}})
            self.assertFalse(body["ok"], bad)
        with self.assertRaises(ModuleError):
            self.host.open_web("x", "file:///C:/secret.txt")


class SystemMonitorTest(HubTestBase):
    def c(self, fn, **kw):
        return self.registry.call("system", fn, kw)

    def test_sample_and_top(self):
        try:
            import psutil  # noqa: F401
        except ImportError:
            self.skipTest("psutil が無い")
        s = self.c("sample")
        for k in ("cpu", "mem", "disk", "io"):
            self.assertIn(k, s)
        self.assertGreater(s["mem"]["total"], 0)
        self.assertIsInstance(self.c("top", n=3), list)

    def test_ping_host_is_validated(self):
        for bad in ("1.1.1.1 & del x", "-t", "a b"):
            _, body = self.post("/api/call", {"module": "system", "fn": "set_prefs", "args": {"pingHost": bad}})
            self.assertFalse(body["ok"], bad)
        self.assertEqual(self.c("set_prefs", pingHost="8.8.8.8")["pingHost"], "8.8.8.8")

    def test_bar_status_off_by_default(self):
        self.assertIsNone(self.c("status"))


class ScriptSyntaxTest(unittest.TestCase):
    """画面の JS に構文エラーがあると、その窓が丸ごと開かなくなる。node があれば全部確かめる。"""

    def test_all_ui_scripts_parse(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node が無い")
        files = [p for p in list((ROOT / "ui").rglob("*.js")) + list((ROOT / "modules").rglob("*.js")) if "vendor" not in p.parts]
        for f in files:
            # import/export を使うので ES モジュールとして確かめる
            r = subprocess.run([node, "--input-type=module", "--check"], input=f.read_text(encoding="utf-8"),
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{f.relative_to(ROOT)}: {r.stderr.strip()[:300]}")

class PdfCompressTest(HubTestBase):
    """ビューアの「圧縮する」（0.13.0）。PyMuPDF が無ければ飛ばす。"""

    def setUp(self):
        super().setUp()
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF が無い")

    def _make(self, name, with_image=True):
        import pymupdf
        p = self.reg_root / "WIP" / name
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), "hello")
        if with_image:
            import random
            rnd = random.Random(1)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1600, 1600), False)
            pix.set_rect(pix.irect, (200, 180, 160))
            for _ in range(4000):                                  # 雑音を入れて、可逆圧縮では縮まない画像にする
                x, y = rnd.randrange(1580), rnd.randrange(1580)
                pix.set_rect(pymupdf.IRect(x, y, x + 20, y + 20), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
            page.insert_image(pymupdf.Rect(72, 100, 272, 300), pixmap=pix)   # 200pt に 1600px = 576dpi
        doc.save(p)
        return self.registry.call("pdf", "open_doc", {"path": str(p)})["key"], p

    def test_standard_shrinks_and_keeps_original(self):
        k, p = self._make("scan.pdf")
        size = p.stat().st_size
        r = self.registry.call("pdf", "compress", {"key": k, "level": "standard"})
        self.assertEqual(r["name"], "scan_圧縮.pdf")
        self.assertLess(r["after"], r["before"] * 0.5)
        self.assertEqual(p.stat().st_size, size)                  # 元は変えない
        r2 = self.registry.call("pdf", "compress", {"key": k, "level": "standard"})
        self.assertEqual(r2["name"], "scan_圧縮 (2).pdf")         # 上書きしない

    def test_no_gain_leaves_nothing(self):
        k, p = self._make("text.pdf", with_image=False)
        r = self.registry.call("pdf", "compress", {"key": k, "level": "light"})
        if not r["path"]:
            self.assertEqual(sorted(x.name for x in p.parent.iterdir() if x.name.startswith((".text", "text_"))), [])
        with self.assertRaises(ModuleError):
            self.registry.call("pdf", "compress", {"key": k, "level": "huge"})


if __name__ == "__main__":
    unittest.main()


class ImageToolTest(HubTestBase):
    """folders.read_image と MCP の folders_read_image（0.8.0）。画像は mcp.images が ON のときだけ Claude に見せる。"""

    def setUp(self):
        super().setUp()
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow が入っていない")
        big = Image.new("RGB", (3000, 2000), (200, 30, 30))
        big.save(self.reg_root / "WIP" / "big.png")
        rot = Image.new("RGB", (400, 200), (0, 0, 255))
        exif = rot.getexif()
        exif[0x0112] = 6                                     # 「90 度回して見る」写真
        rot.save(self.reg_root / "WIP" / "rot.jpg", exif=exif)

    def _decode(self, r):
        import base64
        import io
        from PIL import Image
        return Image.open(io.BytesIO(base64.b64decode(r["data"])))

    def test_resized_to_jpeg(self):
        r = self.call("read_image", registry="WIP", rel="big.png", max_px=1000)
        im = self._decode(r)
        self.assertEqual(im.format, "JPEG")
        self.assertLessEqual(max(im.size), 1000)
        self.assertEqual((r["width"], r["height"]), (3000, 2000))
        r = self.call("read_image", registry="WIP", rel="big.png", max_px=99999)
        self.assertLessEqual(max(self._decode(r).size), 2048)       # 上限に丸める

    def test_exif_orientation_applied(self):
        im = self._decode(self.call("read_image", registry="WIP", rel="rot.jpg"))
        self.assertGreater(im.size[1], im.size[0])                 # 縦長に直っている

    def test_refuses_non_image_and_escape(self):
        with self.assertRaises(ModuleError):
            self.call("read_image", registry="WIP", rel="a.txt")
        (self.outside / "x.png").write_bytes((self.reg_root / "WIP" / "big.png").read_bytes())
        with self.assertRaises(ModuleError):
            self.call("read_image", registry="WIP", rel="../../desktop/x.png")

    def test_raw_without_rawpy_explains(self):
        (self.reg_root / "WIP" / "photo.dng").write_bytes(b"II*\x00fake")
        saved = sys.modules.get("rawpy")
        sys.modules["rawpy"] = None                                # 入っていない状態にする
        try:
            with self.assertRaises(ModuleError) as cm:
                self.call("read_image", registry="WIP", rel="photo.dng")
            self.assertIn("rawpy", str(cm.exception))
        finally:
            if saved is None:
                sys.modules.pop("rawpy", None)
            else:
                sys.modules["rawpy"] = saved

    def test_without_pillow_only_this_tool_fails(self):
        saved = {k: v for k, v in sys.modules.items() if k == "PIL" or k.startswith("PIL.")}
        for k in saved:
            del sys.modules[k]
        sys.modules["PIL"] = None
        try:
            with self.assertRaises(ModuleError) as cm:
                self.call("read_image", registry="WIP", rel="big.png")
            self.assertIn("Pillow", str(cm.exception))
            self.assertTrue(self.call("list_dir", registry="WIP"))  # 他の道具は動く
        finally:
            del sys.modules["PIL"]
            sys.modules.update(saved)

    def _mcp(self, panels, images):
        try:
            import hub_mcp
        except ImportError:
            self.skipTest("mcp が入っていない")
        import copy
        cfg = copy.deepcopy(self.config)
        cfg["dataDir"] = str(Path(self.tmp.name) / "data_mcp")
        cfg["mcp"] = {"panels": panels, "calendar": False, **({} if images is None else {"images": images})}
        return hub_mcp.create_server(cfg)[0]

    def test_mcp_images_off_by_default(self):
        from host.config import DEFAULTS
        self.assertFalse(DEFAULTS["mcp"]["images"])
        call = McpTest._call
        _, err = call(self, self._mcp({"WIP": "read"}, None), "folders_read_image", {"panel": "WIP", "path": "big.png"})
        self.assertTrue(err)

    def test_mcp_hidden_panel_refused(self):
        _, err = McpTest._call(self, self._mcp({}, True), "folders_read_image", {"panel": "WIP", "path": "big.png"})
        self.assertTrue(err)

    def test_mcp_returns_image(self):
        r, err = McpTest._call(self, self._mcp({"WIP": "read"}, True), "folders_read_image",
                               {"panel": "WIP", "path": "big.png", "max_px": 512})
        self.assertFalse(err, r)
        text = repr(r)
        self.assertIn("image/jpeg", text)
        self.assertIn("3000x2000", text)

    _run = McpTest._run


class UploadTest(HubTestBase):
    """/upload/<module>/<fn>: 画面からモジュールへバイト列をそのまま送る（0.8.0）。"""

    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(t, ignore_errors=True))
        mod = t / "upmod"
        (mod / "ui").mkdir(parents=True)
        (mod / "manifest.json").write_text(json.dumps({
            "id": "upmod", "name": "up", "version": "0.1.0", "kind": "panel", "runtime": "python", "api": "api.py",
            "requires": {"hub": ">=0.8", "moduleApi": 1},
            "hub": {"window": "panel", "ui": "ui/panel.js", "upload": ["save"]},
            "exports": [{"fn": "other"}]}), encoding="utf-8")
        (mod / "ui" / "panel.js").write_text("export function mount() {}", encoding="utf-8")
        (mod / "api.py").write_text(
            "got = {}\n"
            "class UpError(Exception):\n    pass\n"
            "def save(data, name='x'):\n"
            "    if name == 'bad':\n        raise UpError('名前が悪い')\n"
            "    got['data'] = data\n    return {'size': len(data), 'name': name}\n"
            "def other(data=b''):\n    return 1\n", encoding="utf-8")
        super().setUp()
        self.server.stop()
        self.store.close()
        self.config["modulePaths"].append(str(t))
        self.host, self.registry, self.server, self.store = build(self.config, NullBackend())
        self.server.start()

    def up(self, path, data, token=None):
        req = urllib.request.Request(f"{self.server.base_url}{path}", data=data, method="POST",
                                     headers={"Content-Type": "application/octet-stream",
                                              "X-Hub-Token": token if token is not None else self.server.token})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_bytes_reach_function(self):
        payload = bytes(range(256)) * 40
        code, body = self.up("/upload/upmod/save?name=a.png", payload)
        self.assertEqual((code, body["ok"]), (200, True), body)
        self.assertEqual(body["data"], {"size": len(payload), "name": "a.png"})
        self.assertEqual(self.registry.modules["upmod"].api.got["data"], payload)

    def test_token_required(self):
        code, _ = self.up("/upload/upmod/save", b"x", token="wrong")
        self.assertEqual(code, 403)

    def test_only_declared_functions(self):
        for path in ["/upload/upmod/other", "/upload/folders/list_dir", "/upload/nope/save"]:
            code, body = self.up(path, b"x")
            self.assertFalse(body["ok"], path)

    def test_module_error_is_readable(self):
        _, body = self.up("/upload/upmod/save?name=bad", b"x")
        self.assertEqual(body["error"], "名前が悪い")

    def test_too_large(self):
        import host.server as srvmod
        saved = srvmod.UPLOAD_MAX
        srvmod.UPLOAD_MAX = 16
        try:
            code, _ = self.up("/upload/upmod/save", b"y" * 64)
        finally:
            srvmod.UPLOAD_MAX = saved
        self.assertEqual(code, 413)


class AccentListTest(unittest.TestCase):
    """色（アクセント）の一覧は 4 か所にある。足すときに 1 か所でも漏れると、設定で選べない・色が付かない。"""

    def test_accent_lists_match(self):
        import re
        from host.config import CHOICES
        names = set(CHOICES[("appearance", "accent")])
        theme = (ROOT / "ui/js/theme.js").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'"(\w+)"', re.search(r"ACCENTS = \[(.*?)\]", theme).group(1))), names)
        css = (ROOT / "ui/css/hub.css").read_text(encoding="utf-8")
        i18n = (ROOT / "ui/js/i18n.js").read_text(encoding="utf-8")
        for a in names - {"aurora"}:                       # aurora は :root の既定値
            self.assertIn(f':root[data-accent="{a}"]', css, a)
        for a in names:
            self.assertIn(f".sw-{a} .swatch-chip", css, a)
            self.assertEqual(i18n.count(f'"set.accent.{a}"'), 2, a)   # 日本語と英語


class PythonVersionTest(unittest.TestCase):
    """起動用の .bat 2 つは同じ Python の版を使う（片方だけ変えると「動く・動かない」が起動方法で変わる）。"""

    def test_bats_use_same_version(self):
        import re
        vers = [re.search(r"^set HUB_PY=([\d.]+)\s*$", (ROOT / b).read_text(encoding="utf-8"), re.M).group(1)
                for b in ("start_hub.bat", "start_hub_debug.bat")]
        self.assertEqual(vers[0], vers[1])

    def test_preferred_python_falls_back_to_current(self):
        from host.app import preferred_python
        self.assertTrue(preferred_python().exists())


class MarkdownViewerTest(HubTestBase):
    """ビューアで Markdown を読む（0.9.3）。表示は画面の markdown.js、ここでは読み込みと関連付けの範囲を見る。"""

    def test_read_markdown_utf8_and_cp932(self):
        md = self.reg_root / "WIP" / "note.md"
        md.write_text("# 見出し\n\n- [x] 済\n", encoding="utf-8")
        r = self.registry.call("pdf", "open_doc", {"path": str(md)})
        self.assertEqual(r["kind"], "md")
        got = self.registry.call("pdf", "read_text", {"key": r["key"]})
        self.assertIn("# 見出し", got["text"])
        self.assertEqual(self.registry.call("pdf", "mtime", {"key": r["key"]}), got["mtime"])
        old = self.reg_root / "WIP" / "old.md"
        old.write_bytes("古いメモ".encode("cp932"))              # メモ帳で保存された古いファイル
        k = self.registry.call("pdf", "open_doc", {"path": str(old)})["key"]
        self.assertEqual(self.registry.call("pdf", "read_text", {"key": k})["text"], "古いメモ")

    def test_markdown_is_opened_by_viewer(self):
        import json as _j
        m = _j.loads((ROOT / "modules/pdf/manifest.json").read_text(encoding="utf-8"))
        self.assertIn(".md", m["hub"]["opens"])
        with self.assertRaises(ModuleError):                    # 画像を Markdown として読まない
            png = self.reg_root / "WIP" / "x.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n")
            self.registry.call("pdf", "read_text", {"key": self.registry.call("pdf", "open_doc", {"path": str(png)})["key"]})

    def test_open_url_only_web(self):
        with self.assertRaises(ModuleError):
            self.host.open_url("javascript:alert(1)")
        with self.assertRaises(ModuleError):
            self.host.open_url("file:///C:/Windows/system32/calc.exe")


class CaptureExcludeTest(HubTestBase):
    """Hub の窓を画面の取り込みから外す（0.10.0。レックスケッチが「画面も」で録る間だけ使う）。"""

    def test_null_backend_reports_unsupported(self):
        r = self.host.set_capture_excluded(True, owner="rec")
        self.assertEqual(set(r), {"on", "supported", "failed", "owners"})
        self.assertTrue(r["on"])
        self.assertFalse(r["supported"])                  # 確認用の表示では窓が無い
        self.assertEqual(r["failed"], [])

    def test_owners_are_counted(self):
        self.host.set_capture_excluded(True, owner="rec")
        self.host.set_capture_excluded(True, owner="other")
        self.assertTrue(self.host.set_capture_excluded(False, owner="rec")["on"])     # まだ other がオン
        self.assertFalse(self.host.set_capture_excluded(False, owner="other")["on"])
        self.assertFalse(self.host.set_capture_excluded(False, owner="nobody")["on"])  # 余分に戻しても平気

    def test_module_can_reach_it_through_ctx(self):
        self.assertTrue(callable(getattr(self.registry.host, "set_capture_excluded", None)))


class ReopenCollapsedTest(HubTestBase):
    """畳んだまま開いているパネルを、もう一度開こうとしたら広げる（0.10.3）。"""

    def test_reopen_expands(self):
        self.host.open_panel("folders:WIP")
        self.host.collapse_panel("folders:WIP", True)
        self.assertEqual(self.host.backend.windows["folders:WIP"]["geom"][3], PANEL_HEADER_H)
        r = self.host.open_panel("folders:WIP")
        self.assertTrue(r["already"])
        self.assertFalse(self.host.panel_state("folders:WIP")["collapsed"])
        self.assertGreater(self.host.backend.windows["folders:WIP"]["geom"][3], PANEL_HEADER_H)
        self.assertEqual(self.host.backend.windows["folders:WIP"].get("reloads"), 1)

    def test_open_after_restart_is_expanded(self):
        self.host.open_panel("folders:WIP")
        self.host.collapse_panel("folders:WIP", True)
        self.host.close_panel("folders:WIP")
        self.host.open_panel("folders:WIP")                       # 次に開くとき（再起動後の復元も同じ）
        self.assertFalse(self.host.panel_state("folders:WIP")["collapsed"])
        self.assertGreater(self.host.backend.windows["folders:WIP"]["geom"][3], PANEL_HEADER_H)


class FolderDropTest(HubTestBase):
    """エクスプローラーからのドロップ（0.10.6）: フォルダを中身でなくフォルダごと、落とした場所へ。"""

    def _ext_folder(self, name="外のフォルダ"):
        d = self.outside / name
        (d / "sub").mkdir(parents=True)
        (d / "a.txt").write_text("a")
        (d / "sub" / "b.txt").write_text("b")
        return d

    def test_folder_moves_as_folder_into_subfolder(self):
        d = self._ext_folder()
        # 画面部品が中のファイルだけを渡してきた場合でも、項目名からフォルダに戻す
        r = self.call("move_in", registry="WIP", paths=[str(d / "a.txt"), str(d / "sub" / "b.txt")],
                      dest_rel="sub", names=["外のフォルダ"])
        self.assertEqual(r["moved"], ["外のフォルダ"])
        self.assertTrue((self.reg_root / "WIP" / "sub" / "外のフォルダ" / "sub" / "b.txt").exists())
        self.assertEqual((self.reg_root / "WIP" / "a.txt").read_text(), "a")   # 元からある a.txt はそのまま
        self.assertFalse(d.exists())

    def test_files_without_names_move_as_before(self):
        f = self.outside / "c.txt"
        f.write_text("c")
        self.call("move_in", registry="WIP", paths=[str(f)], dest_rel="sub")
        self.assertTrue((self.reg_root / "WIP" / "sub" / "c.txt").exists())

    def test_adopt_folder_becomes_panel(self):
        d = self._ext_folder("資料")
        r = self.call("adopt_folders", paths=[str(d / "a.txt")], names=["資料"])
        self.assertEqual(r["added"], ["資料"])
        self.assertIn("資料", [i["id"] for i in self.call("instances")])
        f = self.outside / "x.txt"
        f.write_text("x")
        self.assertTrue(self.call("adopt_folders", paths=[str(f)], names=["x.txt"])["errors"])   # ファイルは不可


class TextNoteTest(HubTestBase):
    """ビューアで txt・rtf を読む、md・txt を「書く」（0.11.0）。"""

    def _open(self, name, data: bytes):
        p = self.reg_root / "WIP" / name
        p.write_bytes(data)
        return self.registry.call("pdf", "open_doc", {"path": str(p)})["key"], p

    def test_read_txt_encodings(self):
        for data, want in ((("メモ帳").encode("cp932"), "メモ帳"), ("﻿BOM付き".encode("utf-8"), "BOM付き"),
                           ("UTF-16".encode("utf-16"), "UTF-16")):
            k, _ = self._open("a.txt", data)
            r = self.registry.call("pdf", "read_text", {"key": k})
            self.assertEqual((r["text"], r["kind"], r["writable"]), (want, "text", True))

    def test_rtf_text_only_and_read_only(self):
        u = "\\" + "u12354?"                                         # 「あ」（\\u の Unicode）
        rtf = ("{\\rtf1\\ansi\\ansicpg932{\\fonttbl{\\f0 MS Mincho;}}{\\*\\generator X;}\\f0 Hello \\b bold\\b0\\par "
               "\\'82\\'a2" + u + "x\\par}")
        k, _ = self._open("b.rtf", rtf.encode("ascii"))
        r = self.registry.call("pdf", "read_text", {"key": k})
        self.assertEqual(r["text"], "Hello bold\nいあx\n")
        self.assertFalse(r["writable"])
        with self.assertRaises(ModuleError):
            self.registry.call("pdf", "write_text", {"key": k, "text": "x", "base_mtime": r["mtime"]})

    def test_rtf_font_charsets(self):
        """Mac のテキストエディット: 「…」は欧文フォント（fcharset0 = cp1252）の 1 バイトで書かれる（0.12.1）。"""
        rtf = ("{\\rtf1\\ansi\\ansicpg932{\\fonttbl\\f0\\fnil\\fcharset128 Hira;\\f1\\fswiss\\fcharset0 Helvetica;}\n"
               "\\f0 \\'82\\'53\n\\f1 \\'85\n\\f0 \\'82\\'52{\\f1 \\'85}\\'82\\'51\\par}")
        k, _ = self._open("mac.rtf", rtf.encode("ascii"))
        self.assertEqual(self.registry.call("pdf", "read_text", {"key": k})["text"], "４…３…２\n")

    def test_rtf_edit_makes_txt_copy(self):
        from unittest import mock
        pdf_api = self.registry.modules["pdf"].api
        rtf = "{\\rtf1\\ansi\\ansicpg932\\f0 \\'82\\'a0\\par}"
        k, p = self._open("d.rtf", rtf.encode("ascii"))
        (p.with_suffix(".txt")).write_text("既にある", encoding="utf-8")
        with mock.patch.object(pdf_api, "_soffice", return_value=None), mock.patch.object(pdf_api, "_rtf_assoc", return_value=""):
            self.assertEqual(self.registry.call("pdf", "read_text", {"key": k})["rtfEdit"], "txt")
            r = self.registry.call("pdf", "rtf_edit", {"key": k})
        self.assertEqual(Path(r["path"]).name, "d (2).txt")                      # 上書きしない
        self.assertEqual(p.with_suffix(".txt").read_text(encoding="utf-8"), "既にある")
        self.assertEqual(Path(r["path"]).read_text(encoding="utf-8-sig").strip(), "あ")
        self.assertTrue(p.exists())                                               # 元の rtf は残す
        with mock.patch.object(pdf_api, "_soffice", return_value=None), mock.patch.object(pdf_api, "_rtf_assoc", return_value="Word.RTF.8"):
            self.assertEqual(pdf_api.rtf_editor(), "word")

    def test_grid_paper_closes_edges(self):
        css = (ROOT / "modules" / "pdf" / "ui" / "markdown.css").read_text(encoding="utf-8")
        self.assertIn("round(down", css)
        js = (ROOT / "modules" / "pdf" / "ui" / "markdown.js").read_text(encoding="utf-8")
        self.assertIn('doc.kind !== "md"', js)                                    # txt では写真・手書きを出さない

    def test_write_keeps_encoding_and_detects_conflict(self):
        import os
        import time
        k, p = self._open("c.txt", "一行目\r\n二行目".encode("cp932"))
        r = self.registry.call("pdf", "read_text", {"key": k})
        w = self.registry.call("pdf", "write_text", {"key": k, "text": "直した\n二行目", "base_mtime": r["mtime"]})
        self.assertFalse(w["conflict"])
        self.assertEqual(p.read_bytes(), "直した\r\n二行目".encode("cp932"))      # 文字コードと改行はそのまま
        time.sleep(0.01)
        p.write_text("Claude が書き換えた", encoding="utf-8")
        os.utime(p, (time.time() + 5, time.time() + 5))
        self.assertTrue(self.registry.call("pdf", "write_text", {"key": k, "text": "上書き？", "base_mtime": w["mtime"]})["conflict"])
        self.assertEqual(p.read_text(encoding="utf-8"), "Claude が書き換えた")   # 上書きしない
        w2 = self.registry.call("pdf", "write_text", {"key": k, "text": "絵文字🙂", "base_mtime": p.stat().st_mtime})
        self.assertEqual(p.read_text(encoding="utf-8"), "絵文字🙂")               # cp932 にない字は UTF-8 に
        self.assertFalse(w2["conflict"])

    def test_new_note(self):
        r = self.call("new_note", registry="WIP", rel="sub")
        self.assertTrue(r["rel"].startswith("sub/メモ "))
        self.assertTrue(r["rel"].endswith(".md"))
        self.assertTrue((self.reg_root / "WIP" / r["rel"]).exists())

    def test_assets_saved_beside_md_and_served(self):
        k, p = self._open("note.md", "# メモ\n".encode("utf-8"))
        api = self.registry.modules["pdf"].api
        r = self.registry.call_upload("pdf", "save_asset", b"\x89PNG\r\n\x1a\nxx", {"key": k, "ext": "png"})
        self.assertTrue(r["rel"].startswith("note_files/img-"))
        self.assertTrue((p.parent / r["rel"]).exists())
        self.assertEqual(api.blob_path(f"{k}/a/{r['rel']}"), (p.parent / r["rel"]).resolve())
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>'
        self.assertTrue(self.registry.call_upload("pdf", "save_asset", svg, {"key": k, "ext": "svg", "kind": "ink"})["rel"].startswith("note_files/ink-"))
        for bad in (b'<svg><script>alert(1)</script></svg>',):
            with self.assertRaises(ModuleError):
                self.registry.call_upload("pdf", "save_asset", bad, {"key": k, "ext": "svg"})
        with self.assertRaises(Exception):
            api.blob_path(f"{k}/a/../../a.txt")                    # md のフォルダの外は渡さない
        kt, _ = self._open("plain.txt", b"x")
        with self.assertRaises(ModuleError):                        # txt には絵を入れられない
            self.registry.call_upload("pdf", "save_asset", b"\x89PNG", {"key": kt, "ext": "png"})


class BarSummonTest(HubTestBase):
    """Ctrl+Alt+H でバーを手前に呼び出す（0.11.2）。📌 で後ろに回っていても出し、もう一度押すか、ほかを触ると戻す。"""

    def test_summon_and_sink(self):
        self.host.create_bar()
        self.host.bar_set(pinned=True)
        self.assertEqual(self.host.backend.windows["bar"].get("z"), "bottom")
        r = self.host.bar_summon()
        self.assertTrue(r["raised"])
        self.assertEqual(self.host.backend.windows["bar"].get("z"), "top")
        self.host.bar_set(sink=True)                              # ほかの窓を触った（画面側から）
        self.assertEqual(self.host.backend.windows["bar"].get("z"), "bottom")
        self.host.bar_summon()
        self.host.bar_summon()                                    # もう一度押すと戻る
        self.assertEqual(self.host.backend.windows["bar"].get("z"), "bottom")
        self.assertIn("_summoned", "".join(self.host.backend.windows["bar"].get("js", [])))


def _office_zip(path, files: dict):
    """テスト用の小さな Office ファイル（中身の XML だけを持つ zip）を作る。"""
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


class OfficeTextTest(HubTestBase):
    """Word / Excel / PowerPoint の文字を読む（0.11.2。Claude が MCP で読む・ビューアの簡易表示）。追加の依存なし。"""

    def setUp(self):
        super().setUp()
        d = self.reg_root / "WIP"
        _office_zip(d / "企画.docx", {"word/document.xml": f'<w:document {W_NS}><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>企画書</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>目的</w:t></w:r><w:r><w:tab/><w:t>確認</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>品番</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>価格</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '</w:body></w:document>'})
        _office_zip(d / "売上.xlsx", {
            "xl/workbook.xml": f'<workbook {S_NS}><sheets><sheet name="売上" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                          '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>',
            "xl/sharedStrings.xml": f'<sst {S_NS}><si><t>月</t></si><si><t>金額</t></si></sst>',
            "xl/worksheets/sheet1.xml": f'<worksheet {S_NS}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                        '<row r="2"><c r="A2" t="inlineStr"><is><t>1月</t></is></c><c r="C2"><f>B2*2</f><v>2400</v></c></row></sheetData></worksheet>'})
        _office_zip(d / "提案.pptx", {
            "ppt/slides/slide2.xml": f'<p:sld {A_NS}><a:p><a:r><a:t>二枚目</a:t></a:r></a:p></p:sld>',
            "ppt/slides/slide1.xml": f'<p:sld {A_NS}><a:p><a:r><a:t>提案</a:t></a:r></a:p><a:p><a:r><a:t>ポイント</a:t></a:r></a:p></p:sld>',
            "ppt/notesSlides/notesSlide1.xml": f'<p:notes {A_NS}><a:p><a:r><a:t>質問を受ける</a:t></a:r></a:p><a:p><a:r><a:t>1</a:t></a:r></a:p></p:notes>'})
        (d / "壊れ.docx").write_bytes(b"not a zip")

    def test_docx(self):
        t = self.call("read_text", registry="WIP", rel="企画.docx")["text"]
        self.assertEqual(t, "# 企画書\n目的\t確認\n品番 | 価格")

    def test_xlsx(self):
        t = self.call("read_text", registry="WIP", rel="売上.xlsx")["text"]
        self.assertEqual(t, "--- シート: 売上 ---\n月\t金額\n1月\t\t2400")     # 計算式は保存されている値

    def test_pptx_order_and_notes(self):
        t = self.call("read_text", registry="WIP", rel="提案.pptx")["text"]
        self.assertEqual(t, "--- スライド 1 ---\n提案\nポイント\n（ノート）質問を受ける\n\n--- スライド 2 ---\n二枚目")

    def test_broken_file_explains(self):
        with self.assertRaises(ModuleError) as cm:
            self.call("read_text", registry="WIP", rel="壊れ.docx")
        self.assertIn("古い形式", str(cm.exception))

    def test_viewer_opens_office(self):
        k = self.registry.call("pdf", "open_doc", {"path": str(self.reg_root / "WIP" / "提案.pptx")})["key"]
        self.assertEqual(self.registry.call("pdf", "doc_info", {"key": k})["kind"], "office")
        self.assertIn("スライド 1", self.registry.call("pdf", "office_text", {"key": k})["text"])
        api = self.registry.modules["pdf"].api
        saved = api._soffice
        api._soffice = lambda: None                                # LibreOffice が無いとき
        try:
            self.assertFalse(self.registry.call("pdf", "office_info", {})["libreoffice"])
            with self.assertRaises(ModuleError):
                self.registry.call("pdf", "office_to_pdf", {"key": k})
        finally:
            api._soffice = saved
