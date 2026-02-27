# Killer-7 SARIF / reviewdog 連携手順

## 概要

Issue #52 で追加した `--sarif` / `--reviewdog` を使い、
Killer-7 の review 結果を SARIF と PR 注釈へ連携する運用手順。

設計方針:
- 既存の native inline 投稿（`--inline`）をデフォルト経路として維持する
- SARIF/reviewdog は補助経路としてオプトインで有効化する

## 前提

- `killer-7 review` が実行できる
- PR レビュー対象リポジトリで `gh` が認証済み
- reviewdog を使う場合は `reviewdog` バイナリが実行環境にある

## ローカル実行

### SARIF だけ生成

```bash
killer-7 review --repo owner/name --pr 123 --sarif
```

生成物:
- `.ai-review/review-summary.json`
- `.ai-review/review-summary.md`
- `.ai-review/review-summary.sarif.json`

### reviewdog で PR 注釈を補助投稿

```bash
killer-7 review --repo owner/name --pr 123 --sarif --reviewdog --reviewdog-reporter github-pr-review
```

補足:
- `--reviewdog` 指定時は SARIF を自動生成する
- `KILLER7_REVIEWDOG_TIMEOUT_S`（正の整数）で reviewdog 実行タイムアウトを調整できる（未指定は既定値）

## GitHub Actions 連携（例）

### 1) SARIF を Code Scanning へアップロード

```yaml
- name: Run Killer-7 review (SARIF)
  run: |
    killer-7 review --repo "$GITHUB_REPOSITORY" --pr "${{ github.event.pull_request.number }}" --sarif

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: .ai-review/review-summary.sarif.json
```

### 2) reviewdog で PR 注釈を補助投稿（任意）

```yaml
- name: Run Killer-7 review with reviewdog
  env:
    REVIEWDOG_GITHUB_API_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    killer-7 review --repo "$GITHUB_REPOSITORY" --pr "${{ github.event.pull_request.number }}" --sarif --reviewdog --reviewdog-reporter github-pr-review
```

## 運用上の注意

- `--reviewdog` は補助経路。品質ゲート判定は既存の review-summary / evidence / inline 制約を優先する
- stale head を検知した場合は fail-fast で終了し、成果物をクリアして再実行を要求する
- `--sarif` / `--reviewdog` を使わない実行では、古い `review-summary.sarif.json` は自動削除される

## GitHub Code Scanning 制限事項（PoC #56 実測結果）

Issue #56 の PoC（2026-02-25 実施）で実測した GitHub Code Scanning の制限値。
詳細: `docs/poc/issue-56-sarif-display.md`

### ファイルサイズ

- 制限: **10 MB（gzip 圧縮後のサイズに適用される）**
- 未圧縮 11.24 MB の SARIF が gzip 1.40 MB で正常アップロードされた
- Killer-7 の通常運用（数十〜数百件の findings）ではサイズ制限に達する可能性は極めて低い

### 結果数上限

| 制限 | 値 | 超過時の動作 |
|---|---|---|
| 表示上限（analysis あたり） | **5,000件** | サイレント切り捨て（severity 上位のみ処理、エラーなし） |
| ハード上限（run あたり） | **25,000件** | 明示的なエラー拒否 |

- 5,001件以上を送信しても `processing_status: "complete"`, `errors: null` が返る
- severity ランク順（error > warning > note）で上位 5,000件のみが反映される
- **ユーザーが切り捨てに気づきにくい** — Killer-7 側でガードレールを実装済み（Issue #57）

### Killer-7 側ガードレール（Issue #57）

- findings が **5,001〜25,000件** の場合、`warnings.txt` に `sarif_result_limit_warning` を記録して注意喚起する
- findings が **25,001件以上** の場合、SARIF出力を fail-fast で停止する

### カテゴリ分割

- 複数 ruleId（K7.P0, K7.P1, K7.P2, K7.P3）を含む SARIF は正常に処理される
- severity 別フィルタリングが可能（error, warning, note）
- `automationDetails.id` が Code Scanning の category として使用される

## LSP warning 是正フェーズ（Issue #59）

### Phase 1 実績（今回）

- 対象: `killer_7/report/sarif_export.py`, `killer_7/cli.py`（SARIF/inline周辺）
- `reportImplicitStringConcatenation`: **29 -> 0**
- `reportUnknown*`: **80 -> 10**
- `killer_7/report/sarif_export.py`: **11 -> 0** warnings
- `killer_7/cli.py`: **217 -> 130** warnings

### Phase 2 分割方針（残課題）

優先順:

1. `killer_7/cli.py` の `reportAny` / `reportExplicitAny`
   - 残件: `reportAny` 95件, `reportExplicitAny` 8件
   - 方針: `argparse.Namespace` の型境界を helper で明示し、`Any` 伝播を局所化する

2. `killer_7/cli.py` の `reportUnusedCallResult`
   - 残件: 21件
   - 方針: 副作用専用呼び出しに `_ = ...` を明示し、意図を固定する

3. テストファイルの warning 解消
   - 対象: `tests/test_cli.py`, `tests/test_sarif_export.py`
   - 方針: 本体ロジック修正と切り離し、型付け専用Issueとして段階的に処理する

4. basedpyright 設定の見直し
   - 対象: `pyproject.toml`
   - 方針: `[tool.basedpyright]` のルールレベル設定を明示し、段階導入可能な閾値を定義する
