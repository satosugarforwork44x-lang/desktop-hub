"""paths.py — アプリの場所と、利用者のデータの置き場所を分ける。

アップデートは「hub フォルダを新しいものに置き換える」だけで済むようにしたい。
そのため、利用者ごとに変わるもの（設定・保存データ・自作モジュール）はアプリのフォルダの外に置く。

  Windows: %LOCALAPPDATA%\\Hub\\   （例: C:\\Users\\you\\AppData\\Local\\Hub）
  その他 : ~/.local/share/hub/
  環境変数 HUB_HOME を指定すると、そこを使う（持ち運び用・テスト用）

  <USER_HOME>/hub.config.json   設定
  <USER_HOME>/data/             保存データ（hub.db・hub.log・各モジュールのキャッシュ）
  <USER_HOME>/modules/          自作・追加モジュール（アップデートで消えない）
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent  # hub/ フォルダ（アプリ本体）


def user_home() -> Path:
    env = os.environ.get("HUB_HOME")
    if env:
        return Path(env).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Hub"
    return Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "hub"
