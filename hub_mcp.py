"""hub_mcp.py — Hub の予定とフォルダ窓を、Claude（Claude Desktop / Claude Code）から使えるようにする MCP サーバー。

  Claude Desktop の claude_desktop_config.json に、次のように書く（設定画面の「Claude との連携」からコピーできる）:
    { "mcpServers": { "hub": { "command": "C:/.../python.exe", "args": ["C:/.../hub/hub_mcp.py"] } } }

考え方:
  ・Hub 本体が起動していなくても動く（同じモジュールと同じ保存先 data/hub.db を直接使う）
  ・見せるのは、設定（mcp.panels）で read / write にしたフォルダ窓だけ。既定はどれも見せない
  ・write にしたフォルダ窓には、成果物（テキスト）を書いてもらえる。移動・名前の変更もそこだけ
  ・ごみ箱へ送る（削除）は Claude には渡さない。移動は「元に戻す」で取り消せる
  ・使うと、予定の件名やファイル名は Claude に送られる（README に明記）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # mcp 2.x
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer
    from mcp.server.fastmcp import Image
    from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from host.app import NullBackend
from host.config import get_in, load_config
from host.registry import ModuleError
from hub import build

INSTRUCTIONS = (
    "Hub is the user's desktop workspace on Windows. It has a read-only calendar (from iCal URLs) and "
    "'folder panels': named folders the user sorts files into (e.g. Inbox, Projects). "
    "Use calendar_* to answer questions about the user's schedule. Use folders_* to find, read or tidy files, "
    "and save deliverables with folders_write_text into a panel whose access is 'write' (see folders_list_panels). "
    "Paths are relative to a folder panel. Moves never overwrite (a ' (2)' suffix is added) and can be undone "
    "with folders_undo. Ask before moving many files. web_shortcuts lists sites the user follows (e.g. news). "
    "To look at a picture in a panel, use folders_read_image (only if the user has turned image sharing on)."
)


def _annotations(read_only: bool, destructive: bool = False) -> ToolAnnotations:
    try:  # mcp 2.x（snake_case）
        return ToolAnnotations(read_only_hint=read_only, destructive_hint=destructive, open_world_hint=False)
    except Exception:  # mcp 1.x（camelCase）
        return ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive, openWorldHint=False)


def create_server(config: dict | None = None, reload=None) -> tuple[MCPServer, object]:
    """MCP サーバーを組み立てる（テストからも使う）。返り値: (server, registry)。
    見せる範囲は設定の mcp.panels（フォルダ窓ごとに hidden / read / write）と mcp.calendar で決める。
    この2つは**呼ばれるたびに設定ファイルから読み直す**ので、Hub の設定画面で変えるとすぐ効く（Claude Desktop の再起動は不要）。
    道具の一覧は固定（全部見せる）にして、許していない操作は呼ばれたときに理由付きで断る。"""
    config = config or load_config()
    _host, registry, _server, _store = build(config, NullBackend())
    if reload is None:
        reload = (lambda: config) if config is not None and config.get("_source") is None else load_config
    mcp = MCPServer("hub", instructions=INSTRUCTIONS)

    def access() -> dict[str, str]:
        try:
            cfg = reload()
        except Exception:  # 設定ファイルを書いている途中などで読めなかったら、起動時の内容を使う
            cfg = config
        return dict(get_in(cfg, ("mcp", "panels"), {}) or {})

    def calendar_shared() -> bool:
        try:
            return bool(get_in(reload(), ("mcp", "calendar"), True))
        except Exception:
            return bool(get_in(config, ("mcp", "calendar"), True))

    def call(module: str, fn: str, **args):
        try:
            return registry.call(module, fn, args)
        except ModuleError as e:
            raise ToolError(str(e)) from None  # 意図したエラー（ToolError）は理由が Claude に届く

    def existing() -> set[str]:
        return {r["id"] for r in call("folders", "instances")}

    def need(panel: str, level: str) -> str:
        """panel が level（read / write）以上で公開されているか確かめる。公開していないものは「無い」と同じ扱い。"""
        got = access().get(panel, "hidden")
        if got == "hidden" or panel not in existing():
            raise ToolError(f"folder panel '{panel}' is not available to Claude (see folders_list_panels)")
        if level == "write" and got != "write":
            raise ToolError(f"folder panel '{panel}' is read-only for Claude")
        return panel

    # ---------- 予定（読み取り） ----------
    def need_calendar() -> None:
        if not calendar_shared():
            raise ToolError("the user has not shared their calendar with Claude (Hub settings)")

    if True:  # 予定の道具（見せるかどうかは呼ばれたときに判定）
        @mcp.tool(annotations=_annotations(True))
        def calendar_upcoming(days: int = 7) -> dict:
            """List the user's calendar events from now through the next `days` days (1-14).
            Each event has title, location, start/end (local time, ISO 8601) and allDay."""
            need_calendar()
            r = call("calendar", "upcoming", days=max(1, min(int(days), 14)), refresh=True)
            return {"configured": r["configured"], "events": r["events"], "warning": r["error"] or None}

        @mcp.tool(annotations=_annotations(True))
        def calendar_next() -> dict:
            """The user's next timed event (all-day events are skipped), or null if there is none."""
            need_calendar()
            return {"next": call("calendar", "status")}

    # ---------- Web ショートカット（一覧だけ。ページの中身は Claude 自身の Web 検索・取得で読む） ----------
    def web_shared() -> bool:
        try:
            return bool(get_in(reload(), ("mcp", "web"), True))
        except Exception:
            return bool(get_in(config, ("mcp", "web"), True))

    @mcp.tool(annotations=_annotations(True))
    def web_shortcuts() -> list[dict]:
        """The user's saved web shortcuts (e.g. news sites they check), as name and URL.
        Hub does not fetch pages; use your own web tools to read a site if needed."""
        if not web_shared():
            raise ToolError("the user has not shared their web shortcuts with Claude (Hub settings)")
        return [{"name": i["name"], "url": i["url"]} for i in call("web", "items")]

    # ---------- フォルダ窓（読み取り） ----------
    @mcp.tool(annotations=_annotations(True))
    def folders_list_panels() -> list[dict]:
        """Folder panels the user has shared with Claude, with access 'read' or 'write'.
        Write panels are where you may save deliverables (e.g. reports) with folders_write_text."""
        have = existing()
        return [{"panel": k, "access": v} for k, v in sorted(access().items()) if v != "hidden" and k in have]

    @mcp.tool(annotations=_annotations(True))
    def folders_list(panel: str, path: str = "") -> dict:
        """List one level of a shared folder panel. `path` is relative to the panel ('' = top).
        Returns items with name, rel (relative path), dir, size (bytes) and mtime (unix time)."""
        r = call("folders", "list_dir", registry=need(panel, "read"), rel=path)
        return {"panel": panel, "path": path, "items": r["items"]}

    @mcp.tool(annotations=_annotations(True))
    def folders_search(query: str, panel: str | None = None, limit: int = 50) -> list[dict]:
        """Find files and folders whose name contains `query` (case-insensitive), in one shared panel or all of them."""
        panels = [need(panel, "read")] if panel else [k for k, v in access().items() if v != "hidden" and k in existing()]
        out: list[dict] = []
        for pnl in panels:
            out += call("folders", "search", query=query, registry=pnl, limit=limit)
        return out[: max(1, int(limit))]

    @mcp.tool(annotations=_annotations(True))
    def folders_read_text(panel: str, path: str, max_chars: int = 200000) -> dict:
        """Read a text file (md, txt, csv, json, html, …), the text of a PDF, or the text of a Word / Excel /
        PowerPoint file (docx: headings as '#', tables as ' | '; xlsx: one tab-separated block per sheet with cached
        formula results; pptx: one block per slide plus speaker notes) from a shared panel.
        PDFs are returned page by page ('--- p.N ---'); scanned pages without text are listed in 'scannedPages'
        with a hint (Hub's PDF viewer can OCR them into a .txt). Large files are truncated."""
        return call("folders", "read_text", registry=need(panel, "read"), rel=path, max_chars=max_chars)

    # ---------- 画像を見る（設定の mcp.images が ON のときだけ。既定は OFF） ----------
    def images_shared() -> bool:
        try:
            return bool(get_in(reload(), ("mcp", "images"), False))
        except Exception:
            return bool(get_in(config, ("mcp", "images"), False))

    @mcp.tool(annotations=_annotations(True))
    def folders_read_image(panel: str, path: str, max_px: int = 1568) -> list:
        """View an image file (jpg, png, webp, gif, bmp, tif, and camera RAW) from a shared panel.
        The image is resized so its longer side is at most `max_px` (256-2048) and sent as JPEG."""
        reg = need(panel, "read")
        if not images_shared():
            raise ToolError("the user has not allowed Claude to view images (Hub settings: Claude integration > share images)")
        r = call("folders", "read_image", registry=reg, rel=path, max_px=max_px)
        import base64
        meta = (f"{r['rel']} — {r['format']}, original {r['width']}x{r['height']}px, "
                f"sent {r['sentWidth']}x{r['sentHeight']}px")
        return [Image(data=base64.b64decode(r["data"]), format="jpeg"), meta]

    # ---------- フォルダ窓（書き込み: write にしたフォルダ窓があるときだけ道具を見せる） ----------
    if True:  # 書き込みの道具（使えるのは「読み書き」にしたフォルダ窓だけ。呼ばれたときに判定）
        @mcp.tool(annotations=_annotations(False))
        def folders_write_text(panel: str, path: str, content: str, overwrite: bool = False) -> dict:
            """Save a text deliverable (md, txt, csv, json, html, …; UTF-8, up to 5 MB) into a write panel.
            Missing subfolders are created. If the file exists: overwrite=false saves as 'name (2).ext';
            overwrite=true sends the old file to the Recycle Bin first. Returns the saved relative path."""
            return call("folders", "write_text", registry=need(panel, "write"), rel=path, content=content,
                        overwrite=overwrite)

        @mcp.tool(annotations=_annotations(False))
        def folders_move(panel: str, paths: list[str], to_panel: str) -> dict:
            """Move items from one write panel to the top of another write panel.
            Never overwrites; can be undone with folders_undo(panel)."""
            if panel == to_panel:
                raise ToolError("panel and to_panel are the same; use folders_move_within")
            return call("folders", "move_to", registry=need(panel, "write"), rels=paths, target=need(to_panel, "write"))

        @mcp.tool(annotations=_annotations(False))
        def folders_move_within(panel: str, paths: list[str], to_path: str = "") -> dict:
            """Move items inside the same write panel into the subfolder `to_path` ('' = top). Can be undone."""
            return call("folders", "move_within", registry=need(panel, "write"), rels=paths, dest_rel=to_path)

        @mcp.tool(annotations=_annotations(False))
        def folders_make_folder(panel: str, path: str = "", name: str = "New folder") -> dict:
            """Create a subfolder named `name` inside `path` of a write panel."""
            return call("folders", "make_folder", registry=need(panel, "write"), rel=path, name=name)

        @mcp.tool(annotations=_annotations(False))
        def folders_rename(panel: str, path: str, new_name: str) -> dict:
            """Rename one item in a write panel. Keeps the file in place."""
            return call("folders", "rename", registry=need(panel, "write"), rel=path, new_name=new_name)

        @mcp.tool(annotations=_annotations(False))
        def folders_undo(panel: str) -> dict:
            """Undo the most recent move or rename in a write panel (up to 30 steps back)."""
            return call("folders", "undo", registry=need(panel, "write"))

    return mcp, registry


def main() -> int:
    mcp, _ = create_server()
    try:
        mcp.run()  # stdio（Claude Desktop が起動して、標準入出力でやり取りする）
    except KeyboardInterrupt:  # 手で起動して Ctrl+C で止めたとき、長いエラー表示を出さない
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
