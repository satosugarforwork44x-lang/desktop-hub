"""registry.py — modules/ を走査し、manifest.json に従ってモジュールを登録・呼び出す。

モジュールの種類（manifest.kind）とHubでの扱い:
  panel    … L2: Hubの中で動く。runtime=python なら api.py の関数を画面から呼べる
  launcher … L1: 既存のコマンド(CLI)を actions の定義どおりに呼ぶだけ。画面はHubが自動で作る
  engine   … 計算エンジン（module-registry 側）。Hubではタイルを出さない
"""
from __future__ import annotations

import importlib.util
import json
import re
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import resolve_path
from .paths import user_home
from .store import Store, ScopedStore

KINDS = {"panel", "launcher", "engine"}


class ModuleError(Exception):
    """利用者に見せてよい（意味の分かる）エラー。"""


@dataclass
class ModuleContext:
    """モジュールの setup(ctx) に渡す道具一式。"""
    id: str
    dir: Path
    config: dict
    store: ScopedStore
    data_dir: Path
    host: Any = None  # 窓操作・パスを開く等（app.Host）


@dataclass
class Module:
    id: str
    dir: Path
    manifest: dict
    api: Any = None                      # python モジュールオブジェクト（runtime=python のとき）
    ctx: ModuleContext | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def hub(self) -> dict:
        return self.manifest.get("hub") or {}

    @property
    def exported(self) -> set[str]:
        return {e["fn"] for e in self.manifest.get("exports", []) if "fn" in e}

    def describe(self) -> dict:
        """バーや画面に渡す情報（ファイルパス等の内部情報は出さない）。"""
        hub = dict(self.hub)
        has_ui = bool(hub.get("ui"))
        return {
            "id": self.id,
            "version": self.manifest.get("version", ""),
            "name": self.manifest.get("name", self.id),
            "summary": self.manifest.get("summary", ""),
            "kind": self.manifest.get("kind"),
            "runtime": self.manifest.get("runtime"),
            "hub": hub,
            "ui": f"/m/{self.id}/{hub['ui']}" if has_ui else None,  # 無ければ汎用画面
            "actions": self.manifest.get("actions", []),
            "locales": self.manifest.get("locales", {}),  # 表示言語ごとの上書き（例: {"en": {"name": ...}}）
            "errors": self.errors,
        }


def _ver(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3]) + (0,) * (3 - len(re.findall(r"\d+", text)[:3]))


def incompatible(requires: dict) -> str | None:
    """manifest の requires を今の Hub と比べる。合わなければ理由、合えば None。
      "requires": { "hub": ">=0.5", "moduleApi": 1 }
    """
    from .version import MODULE_API, VERSION
    api = requires.get("moduleApi")
    if api is not None and int(api) != MODULE_API:
        return f"モジュールの約束の版が違う（モジュール {api} / Hub {MODULE_API}）"
    spec = str(requires.get("hub", "")).strip()
    for cond in filter(None, (c.strip() for c in spec.split(","))):
        m = re.match(r"(>=|<=|==|>|<)?\s*([\d.]+)$", cond)
        if not m:
            return f"requires.hub の書き方が読めない: {cond}"
        op, want = m.group(1) or ">=", _ver(m.group(2))
        have = _ver(VERSION)
        ok = {">=": have >= want, "<=": have <= want, "==": have == want, ">": have > want, "<": have < want}[op]
        if not ok:
            return f"Hub {VERSION} では動かない（必要: {spec}）"
    return None


class Registry:
    def __init__(self, config: dict, store: Store, host: Any = None):
        self.config = config
        self.store = store
        self.host = host
        self.modules: dict[str, Module] = {}
        self.errors: list[str] = []

    # ---------- 読み込み ----------
    def load(self) -> "Registry":
        data_dir = resolve_path(self.config.get("dataDir", "data"))
        for base in self.config.get("modulePaths", ["modules"]):
            base_path = resolve_path(base)
            if not base_path.is_dir() and base_path == (user_home() / "modules"):
                base_path.mkdir(parents=True, exist_ok=True)  # 追加モジュールの置き場所は無ければ作る
            if not base_path.is_dir():
                self.errors.append(f"モジュールの場所が見つからない: {base_path}")
                continue
            for d in sorted(base_path.iterdir()):
                if not d.is_dir() or d.name.startswith(("_", ".")):
                    continue
                if not (d / "manifest.json").exists():
                    continue
                self._load_one(d, data_dir)
        return self

    def _load_one(self, d: Path, data_dir: Path) -> None:
        try:
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception as e:  # 壊れたmanifestは他を巻き込まない
            self.errors.append(f"{d.name}: manifest.json が読めない ({e})")
            return
        mid = manifest.get("id", "")
        mod = Module(id=mid, dir=d, manifest=manifest)
        if mid != d.name:
            self.errors.append(f"{d.name}: manifest.id ({mid}) とフォルダ名が違う")
            return
        if mid in self.modules:
            self.errors.append(f"{mid}: 同じIDのモジュールが複数ある（{d}）")
            return
        if manifest.get("kind") not in KINDS:
            mod.errors.append(f"kind は {sorted(KINDS)} のどれか")
        why = incompatible(manifest.get("requires") or {})
        if why:  # 合わない版のモジュールは読み込まない（他のモジュールは動かす）
            mod.errors.append(why)
            self.modules[mid] = mod
            return

        mod.ctx = ModuleContext(
            id=mid, dir=d,
            config=(self.config.get("modules") or {}).get(mid, {}),
            store=self.store.scoped(mid),
            data_dir=data_dir / mid,
            host=self.host,
        )
        # python製のL2モジュールは api.py を読み込み、setup(ctx) があれば呼ぶ
        if manifest.get("runtime") == "python" and manifest.get("api"):
            try:
                spec = importlib.util.spec_from_file_location(f"hubmod_{mid.replace('-', '_')}", d / manifest["api"])
                api = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(api)
                if hasattr(api, "setup"):
                    api.setup(mod.ctx)
                mod.api = api
                for fn in mod.exported:
                    if not callable(getattr(api, fn, None)):
                        mod.errors.append(f"{manifest['api']} に関数 {fn} がない")
            except Exception as e:
                mod.errors.append(f"api の読み込みに失敗: {e}")
        self.modules[mid] = mod

    def list(self) -> dict:
        return {"modules": [m.describe() for m in self.modules.values()], "errors": self.errors}

    def get(self, mid: str) -> Module:
        if mid not in self.modules:
            raise ModuleError(f"モジュール {mid} は登録されていない")
        return self.modules[mid]

    # ---------- L2: python関数の呼び出し ----------
    def call(self, mid: str, fn: str, args: dict | None) -> Any:
        mod = self.get(mid)
        if mod.api is None:
            raise ModuleError(f"{mid} は呼び出せる関数を持たない（runtime={mod.manifest.get('runtime')}）")
        if fn not in mod.exported:  # manifestで公開した関数だけ呼べる
            raise ModuleError(f"{mid}.{fn} は公開されていない")
        try:
            return getattr(mod.api, fn)(**(args or {}))
        except TypeError as e:
            raise ModuleError(f"{mid}.{fn} の引数が違う: {e}")
        except Exception as e:
            # モジュール自身が定義した例外（FolderError等）は、利用者向けの説明として画面に出す
            if type(e).__module__ == mod.api.__name__:
                raise ModuleError(str(e))
            raise

    def call_upload(self, mid: str, fn: str, data: bytes, args: dict | None) -> Any:
        """画面から送られたバイト列を、モジュールの関数に渡す（manifest の hub.upload に書いた関数だけ）。
        引数（args）はクエリ文字列から来るので、すべて文字列。保存先のパスはモジュール側で決める。"""
        mod = self.get(mid)
        if mod.api is None or fn not in (mod.hub.get("upload") or []) or not callable(getattr(mod.api, fn, None)):
            raise ModuleError(f"{mid}.{fn} はファイルを受け付けない（manifest の hub.upload に無い）")
        try:
            return getattr(mod.api, fn)(data, **(args or {}))
        except TypeError as e:
            raise ModuleError(f"{mid}.{fn} の引数が違う: {e}")
        except Exception as e:
            if type(e).__module__ == mod.api.__name__:
                raise ModuleError(str(e))
            raise

    # ---------- L1: CLIアクションの実行 ----------
    def run_action(self, mid: str, action_id: str, file: str, params: dict | None, timeout: int = 900) -> dict:
        mod = self.get(mid)
        action = next((a for a in mod.manifest.get("actions", []) if a.get("id") == action_id), None)
        if not action:
            raise ModuleError(f"{mid} にアクション {action_id} がない")
        if not file or not Path(file).is_file():
            raise ModuleError(f"ファイルが見つからない: {file}")
        accepts = [e.lower() for e in action.get("accepts", [])]
        if accepts and Path(file).suffix.lower() not in accepts:
            raise ModuleError(f"このアクションが受け付けるのは {', '.join(accepts)} のファイル")

        values = {p["name"]: p.get("default") for p in action.get("params", [])}
        for p in action.get("params", []):  # 定義済みのパラメータだけ受け取る
            if params and p["name"] in params:
                v = params[p["name"]]
                if p.get("type") == "select" and v not in [o["value"] if isinstance(o, dict) else o for o in p.get("options", [])]:
                    raise ModuleError(f"{p['name']} の値が選択肢にない: {v}")
                if p.get("type") == "number":
                    v = float(v)
                    if "min" in p and v < p["min"] or "max" in p and v > p["max"]:
                        raise ModuleError(f"{p['name']} は {p.get('min')}〜{p.get('max')} の範囲")
                    v = int(v) if float(v).is_integer() else v
                values[p["name"]] = v

        tokens = {"python": sys.executable, "module_dir": str(mod.dir), "file": file, **{k: "" if v is None else str(v) for k, v in values.items()}}
        argv = []
        for part in action["run"]:  # 例: ["{python}", "{module_dir}/cli.py", "{file}", "--dpi", "{dpi}"]
            try:
                argv.append(part.format(**tokens))
            except KeyError as e:
                raise ModuleError(f"run の置換名 {e} が params に無い")
        argv = [a for a in argv if a != ""]  # 空の任意引数は落とす

        kwargs: dict = {}
        if os.name == "nt":  # Windowsで黒いコンソール窓を出さない
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            proc = subprocess.run(argv, cwd=str(mod.dir), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired:
            raise ModuleError(f"{timeout}秒で終わらなかったため停止した")

        # CLIの約束: 最後の行に {"outputs": [...]} 形式のJSONを出せば、Hubが結果ファイルを一覧表示する
        result = None
        last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        if last.startswith("{"):
            try:
                result = json.loads(last)
            except json.JSONDecodeError:
                result = None
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "result": result,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
