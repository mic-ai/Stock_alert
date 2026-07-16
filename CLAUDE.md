# CLAUDE.md

このファイルはClaude Codeがこのリポジトリで作業する際に必ず読み込む規約ファイルです。
実装の詳細仕様は `要件定義書.md` を参照してください。このCLAUDE.mdはコーディング規約・
禁止事項・運用上の注意点を定義します。

## プロジェクト概要
日本株・米国株の業種特化型指数（SOX、日経半導体株指数等）のトレンドを毎日自動判定し、
ワイコフメソッドの近似ルールに合致する銘柄をLINEにアラート送信するバッチシステム。
GitHub Actionsのスケジュール実行で毎日自動稼働する。

## 絶対に守るべきルール

1. **AIの推論による判定を実装に含めない**
   すべての銘柄判定ロジック（トレンド判定、ワイコフ近似判定、RSI閾値判定）は、
   `要件定義書.md` の5章に記載された決定的な数値ルール（if-then/閾値比較）のみで実装する。
   LLM APIを呼び出して「この銘柄は買いか売りか」をAIに判断させるコードを書かない。

2. **秘密情報をコードにハードコードしない**
   LINE Messaging APIのチャネルアクセストークン、データベンダーのAPIキー等は、
   すべて `os.environ` 経由で読み込み、GitHub Actionsの `secrets.*` から注入する。
   `.env` ファイルを使う場合は `.gitignore` に必ず追加する。

3. **自動発注コードを実装しない**
   本システムはアラート通知までが範囲。証券会社への自動発注（売買執行）ロジックは
   要求されない限り実装しない。

4. **yfinance利用時のレート制限対策を省略しない**
   個別銘柄データ取得は必ず20銘柄程度ずつのバッチ処理＋バッチ間1秒程度のスリープを入れる。
   取得結果が空の場合は例外を投げず、警告としてログに記録して処理を継続する。

5. **閾値はすべて設定ファイル（config）に外出しする**
   移動平均期間、モメンタム閾値、RSI閾値、ワイコフ近似ルールの数値基準などを
   コード内にマジックナンバーとして埋め込まず、`config.yaml` 等にまとめ、
   後から人間が調整しやすい構成にする。

## リポジトリ構成（想定）
```
main.py                  … エントリーポイント、GitHub Actionsから呼ばれる
├─ data_fetcher.py        … 株価・出来高データ取得（yfinance、データベンダーAPI呼び出し）
├─ indicators.py          … RSI・移動平均等の計算（pandas-ta利用）
├─ trend_rules.py         … 業種指数のトレンド判定ルール
├─ wyckoff_rules.py       … ワイコフ近似ルール（SC/AR/ST/Spring/CHoCH判定）
├─ screener.py            … トレンド判定とワイコフ近似ルールを組み合わせた銘柄スクリーニング
├─ notifier.py            … LINE Messaging APIへの通知送信
├─ config.yaml            … 閾値・スケジュール等の設定値
├─ watchlist.csv          … スクリーニング対象の候補銘柄プール（業種別）
├─ holdings.csv           … 保有銘柄リスト（手動管理）
└─ .github/workflows/
    └─ daily_screening.yml … GitHub Actionsのスケジュール定義
```

## コーディングスタイル
- Python 3.11以上を想定
- 型ヒントを付ける（`def judge_trend(price_series: pd.Series) -> str:` のように）
- 外部API呼び出し箇所は必ず `try/except` で囲み、失敗時のログ出力を行う
- テスト用に、実際のAPI呼び出しをモック化した単体テストを `tests/` に配置することを推奨

## 実装時に確認すべき既知の制約
- LINE Notifyは2025年3月31日に終了済み。**LINE Messaging APIのみを使用する**こと
  （古いチュートリアル記事にLINE Notifyのサンプルコードが多数残っているため、
  実装時にAIが古い情報を参照して誤ってLINE Notify用のコードを生成しないよう注意する）。
- SBI証券は個人向けの汎用APIを提供していない。データ取得にSBI証券APIを使うコードを
  実装しようとしない。
- yfinanceは非公式ライブラリのため、Yahoo Finance側の仕様変更で突然動作しなくなる
  可能性がある。バージョンを `requirements.txt` に固定して明記する。

## 作業の進め方
1. `要件定義書.md` を読み込み、全体設計を把握する
2. `config.yaml` と `watchlist.csv` の雛形を作成する
3. `data_fetcher.py` → `indicators.py` → `trend_rules.py` → `wyckoff_rules.py` →
   `screener.py` → `notifier.py` の順に実装し、各モジュール単体で動作確認する
4. 最後に `main.py` で全体を結合し、GitHub Actionsのワークフローファイルを作成する
5. 実装が要件定義書の閾値・ルールと一致しているか、実装後に差分を確認する
