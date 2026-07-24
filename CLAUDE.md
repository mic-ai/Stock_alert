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

---

## 実装済み内容（2026-07-16）

### システム構成
全モジュールの実装・テスト・GitHub Actionsへのデプロイが完了し、稼働中。

### 通知手段
- LINE Messaging API は未取得のため、**Gmail SMTP** に変更済み
- 必要な GitHub Secrets: `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `NOTIFY_TO_EMAIL`
- 候補銘柄が0件の日はメール送信なし（正常動作）

### 依存ライブラリの注意点
- `pandas-ta` はGitHub Actions環境でインストール不可のため削除済み
- RSIは `indicators.py` 内でWilderの平滑化法（pandas EWM）を使って独自実装
- `pandas<3.0` に上限を設定（pandas-ta互換性問題の名残として維持）

### 監視セクター構成（config.yaml）
| セクター名 | トレンド指数 | 用途 |
|---|---|---|
| semiconductor | ^SOX（米）、2516.T（日） | 半導体銘柄の買い/売り判定 |
| chemicals | XLB（米素材ETF） | 化学銘柄の買い/売り判定 |
| Construction | ITB（米住宅建設ETF） | 建設銘柄の買い/売り判定 |
| Aerospace/Defense | ITA（米航空宇宙防衛ETF） | 航空宇宙・防衛銘柄の買い/売り判定 |
| Biotechnology | XBI（米バイオテクETF） | バイオテク銘柄の買い/売り判定 |
| Quantum Computing | QTUM（米量子コンピューティングETF） | 量子コンピューティング銘柄の買い/売り判定 |
| Nuclear Energy | URA（米ウラン/原子力ETF） | 原子力銘柄の買い/売り判定 |
| Solar Energy | TAN（米太陽光ETF） | 太陽光銘柄の買い/売り判定 |
| Energy Storage | LIT（米リチウム/電池ETF） | 蓄電池銘柄の買い/売り判定 |
| Oil & Gas | XLE（米エネルギーセレクトETF） | 石油・ガス銘柄の買い/売り判定 |
| Commodity/Gold | GLD | 金関連銘柄の買い/売り判定 |
| Commodity/Platinum | PPLT | プラチナ関連銘柄の買い/売り判定 |
| Commodity/Silver | SLV | 銀関連銘柄の買い/売り判定 |
| Non-ferrous Metals | DBB（米ベースメタルETF） | 非鉄金属銘柄の買い/売り判定 |
| REIT | 1343.T（東証REIT指数連動ETF） | REIT銘柄の買い/売り判定 |

### 保有銘柄（holdings.csv）
| ティッカー | 銘柄名 | セクター |
|---|---|---|
| FLNC | Fluence Energy | Energy Storage |
| FSLR | First Solar | Solar Energy |
| HEI | HEICO | Aerospace/Defense |
| INSM | Insmed | Biotechnology |
| IONQ | IonQ Inc | Quantum Computing |
| OKLO | Oklo | Nuclear Energy |
| REGN | Regeneron Pharmaceuticals | Biotechnology |
| RGTI | Rigetti Computing | Quantum Computing |
| RKLB | Rocket Lab | Aerospace/Defense |
| SMR | NuScale Power | Nuclear Energy |
| 1540.T | 純金上場信託 | Commodity/Gold |
| 1541.T | 純プラチナ上場信託 | Commodity/Platinum |
| 1542.T | 純銀上場信託 | Commodity/Silver |
| 1662.T | 石油資源開発 | Oil & Gas |
| 3436.T | SUMCO | semiconductor |
| 4063.T | 信越化学工業 | chemicals |
| 4204.T | 積水化学工業 | chemicals |
| 485A.T | パワーエックス | Energy Storage |
| 5706.T | 三井金属鉱業 | Non-ferrous Metals |
| 6330.T | 東洋エンジニアリング | Construction |
| 6988.T | 日東電工 | chemicals |
| 8951.T | 日本ビルファンド投資法人 | REIT |
| 8985.T | ジャパン・ホテル・リート投資法人 | REIT |

**注意**: holdings.csvのsector列は`config.yaml`の`sector_indexes`および`watchlist.csv`のsector列と
完全一致（大文字小文字・表記含む）していないと、`screener.py`のトレンド判定・売り判定が機能しない
（2026-07-16に発生した実例: `Semiconductors`/`Chemicals`/`Engineering`/`Aerospace`/`Energy/Battery`
といった表記揺れで判定漏れが起きたため統一修正済み）。またyfinance取得のため日本株ティッカーには
必ず`.T`サフィックスを付けること。

### セクター追加手順（今後の運用）
1. `config.yaml` の `sector_indexes` に指数を追加
2. `watchlist.csv` に対象銘柄を追加（買い候補スクリーニング用）
3. `holdings.csv` に保有銘柄を追加（売り候補スクリーニング用）
4. `git add / commit / push` で反映
5. 追加後は必ず以下でsector名の整合性を確認する
   ```
   python3 -c "import pandas as pd, yaml; cfg=yaml.safe_load(open('config.yaml')); s={x['sector'] for x in cfg['sector_indexes']}; h=pd.read_csv('holdings.csv'); w=pd.read_csv('watchlist.csv'); print(set(h['sector'])-s, set(w['sector'])-s)"
   ```
   両方とも空集合であればOK。

### 不具合・運用対応履歴（2026-07-22）

#### 毎日のメールが届かない問題
- **現象**: 2026-07-16以降、スクリーニング結果メールが届かなくなった
- **調査結果**:
  - GitHub Actions の `Daily Stock Screening` ワークフローは正常稼働（全実行が Success）
  - Gmail SMTP の接続も問題なし
  - **根本原因**: 買い候補・売り候補がともにゼロの日は `if buy_candidates:` / `if sell_candidates:` の条件を満たさず、メール送信処理自体が実行されていなかった
- **修正内容** (`main.py` コミット `6eae992`):
  - 候補の有無にかかわらず毎日1通「日次レポート」メールを送信するよう変更
  - 件名: `【株スクリーニング日次レポート】YYYY-MM-DD 買いN件 / 売りN件`
  - 候補ゼロの場合は本文に「なし」と記載
- **運用上の注意**: 候補が出た日は別途詳細な銘柄情報が本文に含まれる。スクリーニング条件
  が厳しすぎて候補が出ない状態が続く場合は `config.yaml` の閾値（RSI上限・モメンタム閾値等）
  の緩和を検討すること。

---

### 既知の不具合と修正履歴（2026-07-16）
- **yfinanceのMultiIndexカラム問題（修正済み）**: `yfinance==0.2.54` は単一銘柄の
  `yf.download()` でも `(Price, Ticker)` のMultiIndexカラムを返すため、`df["Close"]` が
  `pd.Series` ではなく1列の `DataFrame` になり、`trend_rules.judge_trend()` 内の
  `ma_short > ma_long` 比較で `ValueError: The truth value of a Series is ambiguous` が
  発生していた。`data_fetcher.py` に `_flatten_columns()` を追加し、ダウンロード直後に
  MultiIndexの `Ticker` レベルを除去することで解消。この不具合は以前から潜在していたが、
  たまたまYahoo Finance側のレート制限でデータ取得自体が失敗し続けていたため表面化して
  いなかった（`データ空` → `judge_trend` 未実行 → 例外なし、という形で隠れていた）。
  **今後同様の改修をする際は、GitHub Actionsの実行ログで `トレンド判定` が実際にデータ
  ありで実行されたか（`データ不足`/レート制限の警告だけで終わっていないか）を必ず確認
  すること。**
- **GitHub Actionsランナーからのyfinanceレート制限**: `gh workflow run` での手動実行時、
  GitHub-hostedランナーのIPからのアクセスが `YFRateLimitError: Too Many Requests` で
  弾かれ、全銘柄データ取得が失敗するケースが確認されている。この場合でも例外は投げず
  警告ログのみで正常終了する（ルール4の設計通り）が、実質的なスクリーニングは行われて
  いない点に注意。恒常的に発生する場合はリトライ間隔の調整等の対策を検討する。
- **メール配信テスト（Gmail SMTP）**: 2026-07-16に一時的な `test_email.yml`
  ワークフロー（`notifier.send_email()` を直接呼び出すだけの手動実行専用ワークフロー）
  で実送信を確認済み。`GMAIL_USER`/`GMAIL_APP_PASSWORD`/`NOTIFY_TO_EMAIL` の
  GitHub Secretsは正しく設定されており、Gmail SMTP経由の通知は正常に機能する。
  確認後にこのテスト用ワークフローは削除済み。同様のテストが再度必要な場合は、
  `notifier.send_email()` をダミー引数で呼び出すだけの一時ワークフローを追加し、
  確認後に削除する方法が有効（実際の候補銘柄が0件だと `daily_screening.yml` は
  メール送信自体をスキップするため、既存ワークフローの手動実行だけでは配信確認に
  ならない）。

### インデントエラーによる2日連続の実行失敗（2026-07-22〜23、修正済み）
- **現象**: `Daily Stock Screening` ワークフローが2026-07-22・7-23の2日連続で失敗
  （`main.py`が起動直後に例外を吐いて終了、メール自体が送信されない）
- **原因**: コミット`6eae992`（「候補ゼロでも毎日日次レポートを送信」する変更）で
  `main.py`のメール送信ブロックを編集した際、周囲が4スペースインデントの中で
  該当ブロックだけ5〜6スペースの不揃いなインデントになっており、
  `IndentationError: unexpected indent`で即座にクラッシュしていた
  （皮肉にも、「候補ゼロの日にメールが届かない問題」を直そうとした修正が原因で、
  候補の有無を問わず一切メールが届かない、より深刻な状態を招いていた）
- **修正**: `main.py`のインデントを4スペースに統一。あわせて本セッションで進行中だった
  `predictions.csv`記録機能（下記）のコミットと同じ箇所を編集していたため、
  `git rebase origin/main`でコンフリクトを解消し、
  「候補ゼロでも日次レポートを送信」する挙動と的中率記録処理を1つのブロックに統合した
- **教訓**: `main.py`等のエントリーポイントをリモートで直接編集した場合、
  ローカルで作業中の別セッションが古いベースのままコミットすると同じ箇所で
  コンフリクトが起きうる。pushする前に`git fetch`で相手の変更を確認する習慣を徹底する

## 実装済み内容（2026-07-24: 的中率トラッキング機能追加）

要件定義書V1.1（9章）・CLAUDEV1.1.mdに基づき、買い/売り候補アラートの的中率を
追跡・集計する機能を追加。今回の改修範囲は**メールのみ**（LINE Messaging APIは
チャネル未取得のため引き続き対象外。要件定義書V1.1に残るLINE関連記述は将来対応の
留保として扱う）。

### 追加ファイル
- `predictions.csv` … 予測ログ（追記専用、gitで永続化）。列は
  `prediction_id,date,ticker,signal_type,basis_price,eval_due_date,eval_price,result,status`
- `prediction_tracker.py` … 記録・的中判定・集計を行う純粋関数群（`judge_hit`等、
  `today_str`等の日付を引数で受け取り内部で`datetime.now()`を呼ばない設計。単体テスト
  `tests/test_prediction_tracker.py`で境界値・冪等性・集計ロジックを検証）
- `date_utils.py` … `today_jst()`。JST日付を`main.py`/`evaluate.py`で共通利用
- `evaluate.py` … 別エントリーポイント（的中率評価バッチ）。`data_fetcher.fetch_stock_data()`
  を再利用してデータ取得（レート制限対策のバッチ処理・スリープはそのまま踏襲）
- `.github/workflows/daily_evaluation.yml` … 8:10 JST（`cron: "10 23 * * 0-4"`）に
  `evaluate.py`を実行

### 既存ファイルの変更点
- `main.py`: `datetime.now()`（UTC、下記バグ参照）を`date_utils.today_jst()`に変更。
  買い/売り候補が判明した時点で`predictions.csv`に記録（メール送信の成否に関わらず
  無条件で記録。追跡対象はスクリーニングルールの精度でありSMTP成否ではないため）
- `screener.py`: 候補dictに`"close"`（判定に使った終値そのもの）を追加し、
  `basis_price`記録用の再フェッチを不要にした
- `notifier.py`: `format_evaluation_summary()`を追加
- `config.yaml`: `line:`セクション（実体はメールリトライ設定で命名が実態と乖離していた）
  を削除し、`email:`・`evaluation:`セクションに整理

### 運用ルール
- **的中率サマリーメールは、当日評価対象（`eval_due_date<=当日`かつ`status=pending`）が
  0件の日は送信しない**（ユーザー確認済みの方針）。運用開始直後は最短でも`business_days`
  （初期値5営業日）経過するまでメールは届かない
- `status="unavailable"`（評価対象銘柄のデータ取得失敗）はリトライせず永続的に的中率の
  分母から除外する。一時的なレート制限で取得失敗した場合でも再評価はされない設計
- `predictions.csv`の`date`/`basis_price`/`eval_due_date`列は評価バッチで一切書き換えない
  （追記専用、要件定義書V1.1ルール6）。書き換えるのは`eval_price`/`result`/`status`のみ
- GitHub Actionsランナーはステートレスなため、`predictions.csv`への書き込みは両ワークフロー
  末尾の`git commit`＋`push`ステップで永続化している。screening/evaluation両ワークフローに
  同一の`concurrency.group: predictions-csv`を設定し、スケジュール実行の遅延で万一実行が
  重なってもpush競合が起きないよう直列化している

### 修正した潜在バグ
- **UTC/JST日付ズレ**: `main.py`の`date_str`が`datetime.now()`（GitHub Actionsランナーの
  UTC）で計算されており、JST運用（cron `0 23 * * 0-4` = 8:00 JST）の意図する営業日と
  1日ズレる可能性があった。従来はメール件名の表示上のズレに留まっていたが、
  `predictions.csv`の`date`/`eval_due_date`計算の起点になるため今回合わせて修正
  （`date_utils.today_jst()`、`zoneinfo`使用・追加依存なし）
- **pandas dtype起因のTypeError**: `predictions.csv`をCSVから読み込むと`eval_price`/
  `result`の空列がfloat64(NaN)型に推論され、`mark_due_predictions_evaluated()`内で
  文字列（"hit"等）を代入しようとすると`TypeError: Invalid value ... for dtype 'float64'`
  が発生することを実装時のスモークテストで発見・修正済み（該当列を明示的に
  `astype("float64")`/`astype("object")`してから代入する）。今後predictions.csv周りを
  改修する際は、CSV経由で読み込んだDataFrameへの型付き代入は同様の問題が起きうる点に注意
