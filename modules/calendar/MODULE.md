---
name: calendar
description: 次の予定をバーに出し、これからの予定を一覧するときに使う（読み取り専用）
---

# 予定（calendar）

## 何をするか
iCal 形式の URL（Google カレンダーの「iCal 形式の非公開 URL」、Outlook.com の「ICS を公開」、iCloud の公開カレンダー）
を読み、これから 7 日分の予定をパネルに、直近の予定をバーに `next 14:00 定例` の形で出す。

## 設定
パネルの「iCal URL を追加」から登録するか、`hub.config.json` に書く。
```json
"modules": { "calendar": { "urls": ["https://calendar.google.com/calendar/ical/.../basic.ics"] } }
```
※ 非公開 URL を知っている人は予定を読めるので、人に見せない・公開リポジトリに入れない。

## 仕組み
- 10 分ごとに取り直す。取れないときは前回の内容（data/calendar/cache.json）を表示する
- 繰り返し予定（RRULE / EXDATE / 個別に変更した回）は 14 日先まで展開する
- 依存: icalendar（BSD-2-Clause）、python-dateutil（Apache-2.0 / BSD）
