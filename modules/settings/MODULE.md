---
name: settings
description: Hub の設定画面（hub.config.json を画面から編集する）
---

# 設定（settings）

画面から変えた項目だけを `hub.config.json` に書き込む（手で書いた他の項目は残す）。
書き換えてよい項目は host/config.py の `EDITABLE` に限る。

| 項目 | 反映 |
|---|---|
| 表示言語 | すぐ（全部の窓を読み込み直す） |
| バーの位置・タイルの表示 | すぐ（バーだけ作り直す） |
| ウィンドウの角 | すぐ（Windows 11） |
| フォルダの場所 | 再起動が必要 |
| Claude からのファイル操作 | 次に Claude Desktop を起動したとき |
