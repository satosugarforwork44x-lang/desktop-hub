"""hub.py — Hubの起動口。

  python hub.py              … 通常起動（上辺バー＋前回開いていたパネル）
  python hub.py --dev        … 窓を作らずサーバーだけ起動。表示されたURLをブラウザで開いて画面を確認する
  python hub.py --open <ファイル>
                             … ファイルを Hub で開く（PDF など）。Hub が起動中ならその Hub で開く（二重に起動しない）
  python hub.py --import-sidebar <sidebar_data.json>
                             … 旧SidebarToolのフォルダ窓の位置・自動オープン設定を取り込む
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import threading
from pathlib import Path

from host.app import Host, NullBackend
from host.config import load_config, resolve_path
from host.registry import Registry
from host.server import HubServer
from host.store import Store


def build(config: dict, backend, port: int = 0):
    """部品を組み立てる（テストからも使う）。"""
    store = Store(resolve_path(config.get("dataDir", "data")) / "hub.db")
    host = Host(config, store, backend, base_url_fn=lambda: server.base_url)
    registry = Registry(config, store, host).load()
    host.registry = registry
    server = HubServer(host, registry, port=port)
    host.token = server.token
    return host, registry, server, store


def import_sidebar(store_path: Path, sidebar_json: Path) -> int:
    """旧 sidebar_data.json の registries（位置・自動オープン）を folders パネルの状態として取り込む。"""
    data = json.loads(sidebar_json.read_text(encoding="utf-8"))
    store = Store(store_path)
    n = 0
    for name, meta in (data.get("registries") or {}).items():
        x, y, w, h = (meta.get("geometry") or [120, 120, 340, 480])[:4]
        store.set("window", f"folders:{name}", {"x": x, "y": y, "w": w, "h": h,
                                                "open": bool(meta.get("auto_open")), "collapsed": False})
        n += 1
    store.close()
    return n


def _run_file(config: dict) -> Path:
    """起動中の Hub の連絡先（ポートと合言葉）を書いておくファイル。2 つ目の Hub はここを見て頼みごとをする。"""
    return resolve_path(config.get("dataDir", "data")) / "run.json"


def _ask_running(config: dict, op: str, body: dict) -> bool:
    """起動中の Hub があれば、その Hub に op を頼む。頼めたら True。"""
    import urllib.request
    f = _run_file(config)
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/api/host/{op}", method="POST",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Hub-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=3) as r:
            return bool(json.loads(r.read() or b"{}").get("ok"))
    except Exception:  # 連絡先が古い・Hub が落ちている → 自分が起動する
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Hub")
    ap.add_argument("--dev", action="store_true", help="窓を作らずサーバーだけ起動する")
    ap.add_argument("--port", type=int, default=0, help="--dev 時のポート番号（0=自動）")
    ap.add_argument("--config", type=Path, help="設定ファイルのパス")
    ap.add_argument("--import-sidebar", type=Path, help="旧SidebarToolの sidebar_data.json")
    ap.add_argument("--open", dest="open_file", help="このファイルを開く（PDF など）")
    args = ap.parse_args()

    config = load_config(args.config)

    if args.import_sidebar:
        n = import_sidebar(resolve_path(config.get("dataDir", "data")) / "hub.db", args.import_sidebar)
        print(f"取り込み完了: フォルダ窓 {n} 件")
        return 0

    if args.dev:
        host, registry, server, _ = build(config, NullBackend(), port=args.port)
        server.start()
        for e in registry.errors + [f"{m.id}: {err}" for m in registry.modules.values() for err in m.errors]:
            print("⚠", e)
        print(f"Python: {platform.python_version()}  ({sys.executable})")
        print(f"設定: {config['_source']}")
        print(f"バー:   {host.url('bar.html', dock=config['bar'].get('dock', 'top'))}")
        if args.open_file:
            r = host.open_file(args.open_file)
            print(f"開いた: {r.get('url', '')}")
        print("Ctrl+C で終了")
        try:
            server.thread.join()
        except KeyboardInterrupt:
            server.stop()
        return 0

    from host.app import PywebviewBackend, set_app_id, window_bg
    import webview

    try:  # Web ショートカットのミニ窓でのダウンロードを許可する（保存先を聞く画面が出る）
        webview.settings["ALLOW_DOWNLOADS"] = True
    except (AttributeError, TypeError):
        pass  # 古い pywebview には settings が無い

    set_app_id()

    # 黒い画面なし(pythonw)で起動したときは、メッセージを data/hub.log に残す（不具合調査用）
    if sys.stdout is None:
        log_dir = resolve_path(config.get("dataDir", "data"))
        log_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log_dir / "hub.log", "a", encoding="utf-8", buffering=1)

    # 二重に起動しない: すでに Hub が動いていれば、ファイルを開くのだけ頼んで終わる
    if _ask_running(config, "open_file" if args.open_file else "config",
                    {"path": str(Path(args.open_file).resolve())} if args.open_file else {}):
        return 0

    host, registry, server, store = build(config, PywebviewBackend(config.get("windows", {}).get("corners", "round"),
                                                              window_bg(config.get("appearance", {}).get("mode", "dark"))))
    server.start()
    run_file = _run_file(config)
    run_file.parent.mkdir(parents=True, exist_ok=True)
    run_file.write_text(json.dumps({"port": server.port, "token": server.token, "pid": os.getpid()}), encoding="utf-8")
    host.create_bar(intro=True)

    def on_start():
        host.restore_panels()
        from host.app import HOTKEY_LABEL, start_hotkey
        if not start_hotkey(host.bar_summon):        # Ctrl+Alt+H でバーを呼び出す
            print(f"{HOTKEY_LABEL} はほかのアプリが使っているため、バーの呼び出しには使えません")
        # ショートカット（起動時に開く・スタートメニュー・デスクトップ）を今の場所に合わせ直す（裏で。起動を待たせない）
        threading.Thread(target=host.repair_shortcuts, daemon=True).start()
        if args.open_file:
            try:
                host.open_file(args.open_file)
            except Exception as e:  # 開けなくても Hub 自体は動かす
                print(f"開けませんでした: {e}")

    try:
        # ログイン状態（Web ショートカットのミニ窓）や画面の小さな設定を、次の起動にも残す
        from host.paths import user_home
        webview.start(on_start, private_mode=False, storage_path=str(user_home() / "webview"))  # 窓が全部閉じるまでここで待つ
    finally:
        run_file.unlink(missing_ok=True)
    server.stop()
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
