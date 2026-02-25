# PoC: SARIF表示差異（カテゴリ分割・件数上限UI挙動）確認

- Issue: #56
- Epic: `docs/epics/killer-7-epic.md`（K7-19: SARIF/reviewdog連携）
- 実施日: 2026-02-25
- 担当: @ToaruPen

## 目的

Killer-7 が生成する SARIF を GitHub Code Scanning へアップロードした際の:
1. カテゴリ分割（複数 ruleId/priority 混在時）の表示・検索性
2. 件数上限時の UI 挙動（成功・部分反映・拒否）

を実測し、運用ガイド更新の判断材料とする。

## 前提（GitHub公式ドキュメントより）

| 制限項目 | 値（公式） | 超過時の動作（公式） |
|---|---|---|
| SARIFファイルサイズ | 10 MB | エラー拒否（`413 Payload Too Large`） |
| 結果数/run | 25,000件 | 拒否 |
| UI表示上限 | 5,000件 | severity順で上位5,000件のみ表示（サイレント切り捨て） |

参照:
- https://docs.github.com/en/code-security/code-scanning/troubleshooting-sarif-uploads/file-too-large
- https://docs.github.com/en/code-security/code-scanning/troubleshooting-sarif-uploads/results-exceed-limit

## テスト用フィクスチャ

`scripts/poc-sarif-fixtures.py` で生成。

| フィクスチャ | 件数 | compact サイズ | gzip | 検証目的 |
|---|---|---|---|---|
| `category-split` | 20 | 0.02 MB | 0.00 MB | カテゴリ分割表示 |
| `count-100` | 100 | 0.05 MB | 0.01 MB | 基本動作確認 |
| `count-1000` | 1,000 | 0.45 MB | 0.06 MB | 中規模 |
| `count-5000` | 5,000 | 2.25 MB | 0.28 MB | 表示上限直下 |
| `count-5001` | 5,001 | 2.25 MB | 0.28 MB | 表示truncation境界 |
| `count-10000` | 10,000 | 4.49 MB | 0.56 MB | 10MB以下・大規模 |
| `count-25000` | 25,000 | 11.24 MB | 1.40 MB | 結果数上限 + サイズ超過 |
| `count-25001` | 25,001 | 11.24 MB | 1.40 MB | 結果数上限超過 |

## 検証方法

Code Scanning API (`POST /repos/{owner}/{repo}/code-scanning/sarifs`) に gzip + base64 エンコードした SARIF を直接アップロードし、処理結果を API で確認。

アップロードスクリプト: `scripts/poc-sarif-upload.sh`

## 検証結果

### 1. カテゴリ分割検証

**手順:** `category-split.sarif.json`（20件、P0/P1/P2/P3 各5件）をアップロード

**結果:**
- [x] **P0/P1/P2/P3 のアラートが表示される**: analysis に `rules_count: 4` として登録
- [x] **ruleId でフィルタリング可能**: K7.P0, K7.P1, K7.P2, K7.P3 が個別ルールとして認識
- [x] **severity でフィルタリング可能**: API で `severity=error|warning|note` パラメータが有効
  - K7.P0 → error, K7.P1 → error, K7.P2 → warning, K7.P3 → note
- [x] **同一 ruleId のアラートは個別アラートとして表示**: `partialFingerprints` で一意識別

```
Analysis: id=1004011776, results_count=20, rules_count=4, category=killer-7
```

### 2. 件数上限検証

#### 2-1. count-100（基本動作確認）

- アップロード結果: ✅ 成功
- 受理件数: 100件（全件）
- 備考: 正常処理

#### 2-2. count-1000

- アップロード結果: ✅ 成功
- 受理件数: 1,000件（全件）
- 備考: 正常処理

#### 2-3. count-5000（表示上限直下）

- アップロード結果: ✅ 成功
- 受理件数: 5,000件（全件）
- 備考: 上限ちょうどで全件受理

#### 2-4. count-5001（表示truncation境界）

- アップロード結果: ✅ 成功（エラーなし）
- 受理件数: **5,000件**（1件サイレント切り捨て）
- truncation発生: **Yes**
- 備考: `processing_status: "complete"`, `errors: null` — 切り捨てはエラー扱いにならない

```
Analysis: id=1004013287, results_count=5000, rules_count=4
```

#### 2-5. count-10000（大規模・10MB以下）

- アップロード結果: ✅ 成功
- 受理件数: **5,000件**（5,000件サイレント切り捨て）
- truncation発生: Yes
- 備考: 4.49 MB (compact), 0.56 MB (gzip)。サイズ制限内

#### 2-6. count-25000（compact 11.24 MB — サイズ超過テスト）

- アップロード結果: ✅ **成功**
- 受理件数: **5,000件**（20,000件サイレント切り捨て）
- エラーメッセージ: なし（`processing_status: "complete"`, `errors: null`）
- 備考: **未圧縮 11.24 MB だがアップロード成功。gzip 圧縮後 1.40 MB であり、10 MB 制限は圧縮後のサイズに適用されることが判明**

```
Analysis: id=1004017614, results_count=5000, rules_count=4
```

#### 2-7. count-25001（結果数上限超過）

- アップロード結果: ❌ **失敗**
- エラーメッセージ: `"rejecting SARIF, as there are more results per run than allowed (25001 > 25000)"`
- 備考: `processing_status: "failed"` — 25,000件ハード上限は厳密に適用される

### 3. アラート分布（全アップロード累積）

ブランチ上の合計アラート数: **8,500件**

| severity | アラート数 | 対応 ruleId |
|---|---|---|
| error | 5,000 | K7.P0, K7.P1 |
| warning | 2,000 | K7.P2 |
| note | 1,500 | K7.P3 |

## 結論

### カテゴリ分割

✅ **問題なし。** 複数 ruleId/priority を含む SARIF は正常に処理される。

- 4つの ruleId (K7.P0〜K7.P3) はすべて個別ルールとして登録
- severity 別フィルタリングが API で動作確認済み
- Killer-7 の priority → SARIF level マッピング（P0/P1→error, P2→warning, P3→note）は Code Scanning と適合

### 件数上限

⚠️ **5,000件/analysis の表示上限はサイレント切り捨てであり、ユーザーが気づきにくい。**

- 5,001件以上を送信しても `processing_status: "complete"`, `errors: null` が返る
- severity ランク順で上位5,000件のみ処理される
- → Killer-7 側で findings が 5,000件を超える場合は **警告を出す** ガードレールが必要

### サイズ上限

✅ **10 MB 制限は gzip 圧縮後のサイズに適用される。**

- 未圧縮 11.24 MB（25,000件）のSARIFが gzip 1.40 MB で正常アップロードされた
- → Killer-7 の実運用では結果数上限（25,000件）の方が先にヒットするため、サイズ制限は実質的なボトルネックにならない
- ただし、`upload-sarif` action 経由の場合の挙動（action 内部でのサイズチェック）は別途確認が望ましい

### 25,000件ハード上限

❌ **25,001件以上は明確なエラーで拒否される。**

- エラーメッセージ: `"rejecting SARIF, as there are more results per run than allowed (25001 > 25000)"`
- → Killer-7 側で findings が 25,000件を超えないようバリデーションが必要

## 運用ガイド更新提案

検証結果に基づく `docs/operations/sarif-reviewdog.md` への追記:

1. **件数上限ガードレール**: Killer-7 の SARIF 出力で findings が 5,000件を超える場合は警告を表示し、severity 上位のみが Code Scanning に反映される旨をユーザーに通知する
2. **サイズ制限の明文化**: 10 MB 制限は gzip 圧縮後のサイズに適用される。Killer-7 の通常運用（数十〜数百件の findings）ではサイズ制限に達する可能性は極めて低い
3. **結果数ハード上限のバリデーション**: SARIF 出力前に結果数が 25,000件を超えていないことを検証し、超過時は fail-fast でエラーにする

## 後続Issue

- #57: PoC結果の反映と運用ガードレール整備（本PoCの結果をインプットとする）
  - 上記の運用ガイド更新提案を実装
  - `sarif_export.py` に件数バリデーションを追加
