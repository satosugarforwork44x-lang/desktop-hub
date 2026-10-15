"""version.py — Hub の版番号（ここだけを書き換える）。

  MAJOR … モジュールの約束（manifest・ctx・HTTP API）を壊す変更
  MINOR … 機能の追加（今までのモジュールはそのまま動く）
  PATCH … 不具合の修正
モジュールは manifest の "requires": {"hub": ">=0.5"} で、動く版を宣言できる。
"""
VERSION = "0.10.5"
# モジュールとの約束の版。MAJOR と同じ考え方で、壊す変更のときだけ上げる
MODULE_API = 1
