"""config.py — hub.config.json を読み込む。無い項目は既定値で補う。"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .paths import APP_ROOT, user_home

CONFIG_VERSION = 3  # 設定ファイルの形の版。形を変えたら上げて、migrate_config に移し替えを書く

DEFAULTS: dict = {
    # 見た目: mode は dark / light / auto（Windows に合わせる）、accent はグラデーションの色
    "appearance": {"mode": "dark", "accent": "aurora"},
    # 表示言語: auto（OSの言語に合わせる）/ ja / en
    "lang": "auto",
    # dock: top / bottom / left / right。length はバーの長さ(px)。
    # labels: auto（入りきらなければアイコンだけ）/ icons（常にアイコンだけ）/ full（常に文字も出す）
    # length: "auto"（中身に合わせて伸び縮み。画面の幅まで）または数値（px）
    # tiles: タイルの並び（order）と隠すもの（hidden）。値はタイルの id（"web" や "folders:Inbox"）
    # folders: フォルダ窓の出し方。auto（よく使うものだけ並べ、隠したものは「フォルダ」タイルから）/ each（すべて並べる）/ group（「フォルダ」タイル 1 つにまとめる）
    "bar": {"dock": "top", "length": "auto", "onTop": True, "labels": "auto", "intro": True, "folders": "auto",
            "tiles": {"order": [], "hidden": []}},
    # corners: round / small / square（Windows 11 の角丸）
    "windows": {"corners": "round"},
    "panels": {"onTop": False},
    # 同梱のモジュール（アプリの中）と、利用者が足すモジュール（アプリの外。アップデートで消えない）
    "modulePaths": ["modules", str(user_home() / "modules")],
    "dataDir": str(user_home() / "data"),
    # フォルダ窓の置き場所。既定はユーザーフォルダの下の Hub（初回起動時に自動で作る）
    "modules": {"folders": {"root": "~/Hub"}},
    # Claude（MCP）から使える範囲。panels はフォルダ窓ごとに hidden（見せない）/ read / write。
    # 書いていないフォルダ窓は hidden（見せない）。calendar=false なら予定も見せない。web=false なら Web ショートカットの一覧も見せない
    "mcp": {"calendar": True, "web": True, "panels": {}},
}

USER_CONFIG = user_home() / "hub.config.json"
LEGACY_CONFIG = APP_ROOT / "hub.config.json"   # 0.4 までの置き場所（アプリの中）
# 設定画面から変えてよい項目（これ以外は書き換えない）
EDITABLE = {
    ("lang",): str, ("appearance", "mode"): str, ("appearance", "accent"): str, ("bar", "dock"): str, ("bar", "labels"): str, ("bar", "intro"): bool, ("bar", "tiles"): dict, ("bar", "folders"): str, ("windows", "corners"): str,
    ("modules", "folders", "root"): str, ("mcp", "calendar"): bool, ("mcp", "web"): bool, ("mcp", "panels"): dict,
}
MCP_ACCESS = {"hidden", "read", "write"}
CHOICES = {
    ("lang",): {"auto", "ja", "en"}, ("appearance", "mode"): {"auto", "dark", "light"},
    ("appearance", "accent"): {"aurora", "ocean", "ember", "graphite"}, ("bar", "dock"): {"top", "bottom", "left", "right"},
    ("bar", "labels"): {"auto", "icons", "full"}, ("windows", "corners"): {"round", "small", "square"},
    ("bar", "folders"): {"auto", "each", "group"},
}


def _merge(base: dict, override: dict) -> dict:
    """辞書を入れ子ごと上書きマージする（override 側が優先）。"""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def migrate_legacy_files() -> list[str]:
    """0.4 まではアプリの中にあった設定と保存データを、利用者の場所へ写す（1回だけ・元は消さない）。"""
    done = []
    home = user_home()
    if LEGACY_CONFIG.exists() and not USER_CONFIG.exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_CONFIG, USER_CONFIG)
        LEGACY_CONFIG.rename(LEGACY_CONFIG.with_name("hub.config.json.migrated"))
        done.append(f"設定を {USER_CONFIG} へ移しました")
    old_data, new_data = APP_ROOT / "data", home / "data"
    if (old_data / "hub.db").exists() and not (new_data / "hub.db").exists():
        shutil.copytree(old_data, new_data, dirs_exist_ok=True)
        done.append(f"保存データを {new_data} へ写しました")
    return done


def migrate_config(data: dict) -> tuple[dict, bool]:
    """古い形の設定を今の形に直す。直したら (新しい中身, True)。"""
    data = copy.deepcopy(data)
    ver = int(data.get("configVersion", 1))
    changed = False
    if ver < 2:
        # 0.4: Claude 連携の mcp.write（全体で ON/OFF）を、フォルダ窓ごとの mcp.panels に置き換えた。
        # どのフォルダ窓を見せるかは利用者が選ぶので、自動では何も見せない（安全側）
        mcp = data.get("mcp")
        if isinstance(mcp, dict) and "write" in mcp:
            mcp.pop("write")
        # 0.5: dataDir "data"（アプリの中）は、利用者の場所へ移した
        if data.get("dataDir") == "data":
            data.pop("dataDir")
        if data.get("modulePaths") == ["modules"]:
            data.pop("modulePaths")
        ver, changed = 2, True
    if ver < 3:
        # 0.6: "theme": "midnight" を、明るさと色を分けた "appearance" に置き換えた
        if "theme" in data:
            data.pop("theme")
        ver, changed = 3, True
    data["configVersion"] = ver
    return data, changed


def load_config(path: Path | None = None) -> dict:
    """設定を読む。無ければ既定値（設定ファイルは設定画面で保存したときに作られる）。
    path を省いたときは、古い置き場所からの引っ越しと、古い形の設定の移し替えもここで行う。"""
    if path is None:
        migrate_legacy_files()
        (user_home() / "modules").mkdir(parents=True, exist_ok=True)
    candidates = [path] if path else [USER_CONFIG]
    for candidate in candidates:
        if candidate and candidate.exists():
            with open(candidate, encoding="utf-8") as f:
                raw = json.load(f)
            raw, changed = migrate_config(raw)
            if changed and path is None:
                _write_json(candidate, raw)
            cfg = _merge(DEFAULTS, raw)
            cfg["_source"] = str(candidate)
            return cfg
    cfg = copy.deepcopy(DEFAULTS)
    cfg["_source"] = "(defaults)"
    return cfg


def resolve_path(p: str) -> Path:
    """設定内の相対パスは hub/ フォルダ基準で解決する。"""
    path = Path(p).expanduser()
    return path if path.is_absolute() else (APP_ROOT / path).resolve()


def get_in(d: dict, keys: tuple, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def save_settings(changes: dict[str, object], path: Path | None = None) -> dict:
    """設定画面からの変更を hub.config.json に書き込む。changes のキーは "bar.dock" のようなドット区切り。
    ファイルにある他の項目（手で書いたもの）は残す。書き込んだ後の、ファイルの中身を返す。"""
    path = path or USER_CONFIG
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for dotted, value in changes.items():
        keys = tuple(dotted.split("."))
        if keys not in EDITABLE:
            raise ValueError(f"この項目は設定画面から変えられません: {dotted}")
        typ = EDITABLE[keys]
        if not isinstance(value, typ):
            raise ValueError(f"{dotted} の値の型が違います")
        if keys in CHOICES and value not in CHOICES[keys]:
            raise ValueError(f"{dotted} に使えない値です: {value}")
        if keys == ("modules", "folders", "root") and not str(value).strip():
            raise ValueError("フォルダの場所が空です")
        if keys == ("bar", "tiles"):
            clean = {}
            for k in ("order", "hidden"):
                v = value.get(k, [])
                if not isinstance(v, list) or not all(isinstance(x, str) and 0 < len(x) < 200 for x in v):
                    raise ValueError(f"bar.tiles.{k} はタイル id の一覧")
                clean[k] = list(dict.fromkeys(v))[:300]
            value = clean
        if keys == ("mcp", "panels"):
            bad = [k for k, v in value.items() if not isinstance(k, str) or v not in MCP_ACCESS]
            if bad:
                raise ValueError(f"mcp.panels の値は hidden / read / write のどれか: {bad}")
            value = {k: v for k, v in value.items() if v != "hidden"}  # 見せないものは書かない（既定が hidden）
        cur = data
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value
    data.setdefault("configVersion", CONFIG_VERSION)
    _write_json(path, data)
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # 途中で落ちても壊れないよう、書き終えてから置き換える
