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

| 制限項目 | 値 | 超過時の動作 |
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

### 注意

- compact 25,000件 = 11.24 MB（> 10 MB）
- `upload-sarif` が gzip 前後どちらのサイズで判定するかは実測で確認

## 検証手順

### 準備

1. `feature/issue-56-poc-sarif-display-verification` ブランチを push
2. GitHub UI → Actions → `poc-sarif-upload` を手動実行

### 1. カテゴリ分割検証

**手順:**
1. `poc-sarif-upload` workflow を `category-split` で実行
2. Security → Code Scanning → アラート一覧を確認

**確認項目:**
- [ ] P0/P1/P2/P3 のアラートが表示されるか
- [ ] ruleId（K7.P0, K7.P1, K7.P2, K7.P3）でフィルタリングできるか
- [ ] severity（error, warning, note）でフィルタリングできるか
- [ ] 同一 ruleId のアラートがグループ化されるか

**結果:**

<!-- 以下に実測結果を記録 -->

```
TODO: スクリーンショットまたはテキストで結果を記録
```

### 2. 件数上限検証

**手順:**
各フィクスチャを順に `poc-sarif-upload` で実行し、結果を記録する。

#### 2-1. count-100（基本動作確認）

- アップロード結果: <!-- 成功 / 失敗 -->
- 表示件数: <!-- N件 -->
- 備考:

#### 2-2. count-1000

- アップロード結果:
- 表示件数:
- 備考:

#### 2-3. count-5000（表示上限直下）

- アップロード結果:
- 表示件数:
- 備考:

#### 2-4. count-5001（表示truncation境界）

- アップロード結果:
- 表示件数:
- truncation発生: <!-- Yes / No -->
- 備考:

#### 2-5. count-10000（大規模・10MB以下）

- アップロード結果:
- 表示件数:
- truncation発生:
- 備考:

#### 2-6. count-25000（compact 11.24 MB — サイズ超過テスト）

- アップロード結果: <!-- 成功 / 失敗 -->
- エラーメッセージ:
- 備考: <!-- gzip圧縮後は1.40 MB。upload-sarifがどちらで判定するか確認 -->

#### 2-7. count-25001（結果数上限超過）

- アップロード結果:
- エラーメッセージ:
- 備考:

## 結論

### カテゴリ分割

<!-- 検証後に記入 -->

### 件数上限

<!-- 検証後に記入 -->

### サイズ上限

<!-- 検証後に記入: 10 MB制限はgzip前/後どちらか -->

## 運用ガイド更新提案

<!-- 検証結果に基づいて、docs/operations/sarif-reviewdog.md への追記内容を提案 -->

1. <!-- 提案1 -->
2. <!-- 提案2 -->
3. <!-- 提案3 -->

## 後続Issue

- #57: PoC結果の反映と運用ガードレール整備（本PoCの結果をインプットとする）
