# Issue #59: LSP warning是正（SARIF/inline関連 第1フェーズ）

## TL;DR

> **Quick Summary**: basedpyright のwarningを SARIF export + review CLI周辺から段階的に削減する。Phase 1 として `reportUnknown*` と `reportImplicitStringConcatenation` を優先的に解消。
> 
> **Deliverables**:
> - `sarif_export.py` の全14 warnings解消
> - `cli.py` の priority warnings（reportUnknown* + reportImplicitStringConcatenation）削減
> - ベースライン記録（変更前後のwarning数）
> - 残課題の Phase 2 分割方針ドキュメント
> 
> **Estimated Effort**: Short（50-150行）
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Tasks 2,3 → Task 4

---

## Context

### Original Request
GitHub Issue #59 — `chore: LSP warning是正（SARIF/inline関連の第1フェーズ）`

LSP（basedpyright 1.37.4）のwarningを、SARIF exportとreview CLI周辺の実装から段階的に是正する。「新規warningを増やさない」だけでなく既存warningの削減を行う。

### Current Warning Baseline

| File | Total | reportUnknown* | reportImplicitStringConcatenation | Other |
|---|---|---|---|---|
| `killer_7/report/sarif_export.py` | 14 | 8 | 4 | 2 (reportUnnecessaryIsInstance, reportUnreachable) |
| `killer_7/cli.py` | 219 | ~13 | 26 | 180 (reportAny, reportUnusedCallResult, etc.) |
| `tests/test_sarif_export.py` | ~5 | ~3 | 0 | 2 |
| `tests/test_cli.py` | ~462 | ~8 | 0 | 454 |

### Interview Summary
**Key Discussions**:
- Phase 1 スコープ: SARIF export + review CLI周辺に限定
- 優先warning: `reportUnknown*` + `reportImplicitStringConcatenation`
- mainに既存の未コミット変更あり → worktreeで分離作業

**Research Findings**:
- basedpyright 1.37.4 使用。`reportAny`/`reportExplicitAny` は basedpyright 固有（Phase 1 対象外）
- `reportImplicitStringConcatenation` は隣接する文字列リテラルに `+` を追加する機械的修正
- `reportUnknownVariableType` は `Mapping[str, object].items()` や `list` イテレーションでの Unknown 伝播が原因 → ループ変数に型注釈追加
- pyproject.toml に basedpyright 設定なし → Phase 2 で検討

### Metis Review
**Identified Gaps** (addressed):
- `reportUnnecessaryIsInstance` (L95) + `reportUnreachable` (L96): パラメータ型が `Mapping[str, object]` のため isinstance は常に True → ランタイム安全性のため `# pyright: ignore[reportUnnecessaryIsInstance]` で抑制（削除しない）
- cli.py の `reportAny` (61件): argparse等の外部ライブラリ由来 → Phase 2 で `allowedUntypedLibraries` 検討
- テストファイルの `reportAny` (351件): Phase 1 対象外、Phase 2 文書に記載

---

## Work Objectives

### Core Objective
SARIF export + review CLI 周辺の LSP warning を削減し、差分レビューの信頼性を向上させる。

### Concrete Deliverables
- `killer_7/report/sarif_export.py`: 14 warnings → 0
- `killer_7/cli.py`: reportUnknown* + reportImplicitStringConcatenation の削減（~39件対象）
- `docs/operations/sarif-reviewdog.md`: 変更があれば更新
- AC4残課題ドキュメント: issue comment または docs に Phase 2 分割方針

### Definition of Done
- [ ] AC1: 対象ファイルのwarning内訳（種類・件数）を再現可能な手順で記録
- [ ] AC2: reportUnknown* / reportImplicitStringConcatenation を優先解消
- [ ] AC3: `python3.11 -m unittest discover -s tests -p 'test*.py'` → 264 tests PASS
- [ ] AC4: 残課題の Phase 2 分割方針を明記

### Must Have
- sarif_export.py の全 warning 解消（14→0）
- cli.py の reportImplicitStringConcatenation 解消（26件）
- cli.py の reportUnknownVariableType 解消（SARIF/review セクション）
- 全264テスト通過、機能回帰なし
- ベースライン（Before/After）の記録

### Must NOT Have (Guardrails)
- `cli.py` の `reportAny` / `reportExplicitAny` / `reportUnusedCallResult` は Phase 1 対象外。触らない。
- テストファイルの warning は、ソースファイル変更に起因するものだけ対応。大規模な型注釈追加はしない。
- `pyproject.toml` への basedpyright 設定追加は Phase 2。
- `# type: ignore` の濫用禁止。最小限の `# pyright: ignore[rule]` のみ、理由コメント付きで許可。
- 挙動を変更するリファクタリングは不可。型注釈追加と文字列結合演算子追加のみ。
- `TypedDict` の導入は Phase 1 対象外（影響範囲が大きいため）。

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-after（既存テストで回帰確認）
- **Framework**: `python3.11 -m unittest`
- **Test count baseline**: 264 tests, all passing

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Source changes**: Use Bash (basedpyright) — Run type checker, count warnings, compare to baseline
- **Test regression**: Use Bash (python3.11 -m unittest) — Run full test suite, assert 0 failures

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Setup — sequential, single task):
└── Task 1: Worktree setup + baseline recording [quick]

Wave 2 (Core fixes — MAX PARALLEL, 2 tasks):
├── Task 2: Fix sarif_export.py warnings (all 14) [quick]
└── Task 3: Fix cli.py priority warnings (reportImplicitStringConcatenation + reportUnknown*) [unspecified-high]

Wave 3 (Verification + Documentation — sequential):
└── Task 4: Test verification + docs update + AC4 documentation [quick]

Wave FINAL (After ALL tasks — independent review, 4 parallel):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)

Critical Path: Task 1 → Task 2/3 → Task 4 → F1-F4
Parallel Speedup: Wave 2 は 2 タスク並列
Max Concurrent: 2 (Wave 2)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| T1 | — | T2, T3 |
| T2 | T1 | T4 |
| T3 | T1 | T4 |
| T4 | T2, T3 | F1-F4 |
| F1-F4 | T4 | — |

### Agent Dispatch Summary

- **Wave 1**: 1 task — T1 → `quick`
- **Wave 2**: 2 tasks — T2 → `quick`, T3 → `unspecified-high`
- **Wave 3**: 1 task — T4 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. Worktree セットアップ + ベースライン記録 (AC1)

  **What to do**:
  - `git worktree add ../Killer-7-issue-59 -b chore/issue-59-lsp-warning-phase1 main` でworktree作成
  - worktree内で `basedpyright --outputjson` を使い、対象4ファイルのwarning内訳を記録
  - 記録フォーマット: ファイル名、warning種別、件数、行番号リスト
  - 記録先: `.sisyphus/evidence/task-1-baseline.json`（JSON形式）
  - 目視確認用サマリー: `.sisyphus/evidence/task-1-baseline-summary.txt`

  **Must NOT do**:
  - ソースコードの変更は一切行わない
  - basedpyright の設定変更はしない

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 単純なコマンド実行とファイル出力のみ。判断不要。
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `git-master`: worktreeの作成は単一コマンドで完了するため不要

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (single)
  - **Blocks**: Task 2, Task 3
  - **Blocked By**: None (can start immediately)

  **References**:

  **Pattern References**:
  - `killer_7/report/sarif_export.py` — 対象ファイル（14 warnings）
  - `killer_7/cli.py` — 対象ファイル（219 warnings）
  - `tests/test_sarif_export.py` — テスト対象
  - `tests/test_cli.py` — テスト対象

  **External References**:
  - basedpyright `--outputjson` フラグ: JSON形式で診断結果を出力

  **WHY Each Reference Matters**:
  - 対象ファイルのパスは basedpyright コマンドの引数として必要
  - `--outputjson` はwarning内訳を構造化データで記録するため（grep/sedよりも信頼性が高い）

  **Acceptance Criteria**:
  - [ ] worktree `../Killer-7-issue-59` が作成され、`chore/issue-59-lsp-warning-phase1` ブランチが存在
  - [ ] `.sisyphus/evidence/task-1-baseline.json` に全対象ファイルのwarning内訳が記録されている
  - [ ] `.sisyphus/evidence/task-1-baseline-summary.txt` にサマリーが記録されている

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: ベースライン記録の完全性確認
    Tool: Bash
    Preconditions: worktreeが作成済み
    Steps:
      1. `cat .sisyphus/evidence/task-1-baseline.json | python3.11 -m json.tool` で JSON バリデーション
      2. JSON内に `killer_7/report/sarif_export.py` のエントリが存在し、warning count = 14 であること
      3. JSON内に `killer_7/cli.py` のエントリが存在し、warning count = 219 であること
      4. `cat .sisyphus/evidence/task-1-baseline-summary.txt` でサマリーが人間可読であること
    Expected Result: JSON valid、sarif_export.py=14, cli.py=219
    Failure Indicators: JSONパースエラー、warning数の不一致、ファイル不在
    Evidence: .sisyphus/evidence/task-1-baseline-validation.txt

  Scenario: Worktreeの正常性確認
    Tool: Bash
    Preconditions: Task完了後
    Steps:
      1. `git -C ../Killer-7-issue-59 branch --show-current` → `chore/issue-59-lsp-warning-phase1`
      2. `git -C ../Killer-7-issue-59 status --short` → clean working tree
    Expected Result: 正しいブランチ名、クリーンな作業ツリー
    Failure Indicators: ブランチ名不一致、未追跡ファイルの存在
    Evidence: .sisyphus/evidence/task-1-worktree-status.txt
  ```

  **Commit**: NO（セットアップのみ）

---

- [ ] 2. sarif_export.py の全warning解消（14 → 0）

  **What to do**:

  **A. `reportImplicitStringConcatenation` (4件: L97, L104, L110, L117)**
  隣接文字列リテラルに明示的な `+` 演算子を追加。例:
  ```python
  # Before (warning)
  raise ValueError(
      "Invalid review summary: missing required scope_id "
      f"(summary_type={type(summary).__name__}, summary_keys={summary_keys})"
  )
  # After (fixed)
  raise ValueError(
      "Invalid review summary: missing required scope_id "
      + f"(summary_type={type(summary).__name__}, summary_keys={summary_keys})"
  )
  ```

  **B. `reportUnknownVariableType` + `reportUnknownArgumentType` (8件)**
  - L26: `for key_obj, mapped_value in value.items():` → `for key_obj, mapped_value in value.items():` に型注釈追加
    - `value` は `Mapping[str, object]` なので `.items()` は `ItemsView[str, object]` を返すが、basedpyrightが推論できていない
    - Fix: `key_obj: str` の型注釈が不可なら、内部で `assert isinstance(key_obj, str)` の縮小表明を利用
  - L45: `for item in value:` → `value` は `list` 型（`isinstance` チェック後）だが要素型が不明
    - Fix: `item: object` の型注釈追加、または `cast` が必要なら `list[object]` への narrowing
  - L113-114: `findings = raw_findings` → `findings: list[object] = raw_findings`
    - `raw_findings` は `isinstance(raw_findings, list)` チェック後だが `list[Unknown]` になる
    - Fix: 明示的型注釈で `list[object]` に絞る
  - L125-126: `for item in findings:` → `item: object` 型注釈追加
    - 上記 findings の型修正に連動して解消される可能性あり

  **C. `reportUnnecessaryIsInstance` + `reportUnreachable` (2件: L95-96)**
  - `summary` パラメータは既に `Mapping[str, object]` 型なので `isinstance(summary, Mapping)` は常に True
  - **ランタイム安全性のため削除しない**。代わりに抑制コメントを使用:
  ```python
  if not isinstance(summary, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance] — runtime guard for untyped callers
      raise ValueError(
          "Invalid review summary: expected mapping at root "
          + f"(summary_type={type(summary).__name__})"
      )
  ```
  - `reportUnreachable` (L96) は isinstance の抑制により自動解消されるはずだが、されない場合は同様に `# pyright: ignore[reportUnreachable]` を追加

  **Must NOT do**:
  - 関数シグネチャの変更（パブリックAPIの型を変えない）
  - `TypedDict` の導入
  - ロジックの変更（型注釈と文字列結合演算子の追加のみ）
  - `# type: ignore` の使用（`# pyright: ignore[specific-rule]` のみ許可）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 14件の機械的修正。型注釈追加と文字列結合演算子の追加のみ。判断が必要なのは reportUnnecessaryIsInstance の処理のみ。
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `tdd-protocol`: 既存テストの回帰確認のみ。新規テスト作成は不要。

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 4
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `killer_7/report/sarif_export.py:22-29` — `_coerce_str_object_dict`: L26 `key_obj` の Unknown warning の原因箇所
  - `killer_7/report/sarif_export.py:40-51` — `_as_sources`: L45 `item` の Unknown warning の原因箇所
  - `killer_7/report/sarif_export.py:94-121` — `review_summary_to_sarif` 前半: isinstance/Unreachable/ImplicitStringConcat/Unknown が集中
  - `killer_7/report/sarif_export.py:125-126` — findings ループ: item の Unknown warning

  **External References**:
  - basedpyright `# pyright: ignore[ruleName]` 構文: 特定のルールのみを抑制するインラインコメント

  **WHY Each Reference Matters**:
  - 各行番号は具体的なwarning発生箇所。エージェントはこれらの行を直接編集する
  - 関数シグネチャと周囲の型の流れを理解してから修正するため、関数全体の範囲を参照

  **Acceptance Criteria**:
  - [ ] `basedpyright killer_7/report/sarif_export.py 2>&1 | grep -c "warning:"` → `0`
  - [ ] `python3.11 -m unittest tests.test_sarif_export` → PASS

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: sarif_export.py の warning ゼロ確認
    Tool: Bash
    Preconditions: Task 2 の全修正が完了
    Steps:
      1. `basedpyright killer_7/report/sarif_export.py 2>&1 | grep -c "warning:"` を実行
      2. 結果が `0` であることを確認
      3. `basedpyright killer_7/report/sarif_export.py 2>&1 | grep -c "error:"` → `0` であること
    Expected Result: 0 warnings, 0 errors
    Failure Indicators: warning カウント > 0、または新規 error の発生
    Evidence: .sisyphus/evidence/task-2-sarif-warning-count.txt

  Scenario: sarif_export.py のテスト回帰確認
    Tool: Bash
    Preconditions: Task 2 の全修正が完了
    Steps:
      1. `python3.11 -m unittest tests.test_sarif_export -v 2>&1` を実行
      2. 出力に "FAILED" が含まれないことを確認
      3. 終了コード = 0 であること
    Expected Result: 全テスト PASS、終了コード 0
    Failure Indicators: "FAILED" または "ERROR" が出力に含まれる
    Evidence: .sisyphus/evidence/task-2-sarif-test-result.txt

  Scenario: 型注釈の正当性確認（行動変更なし）
    Tool: Bash
    Preconditions: Task 2 の全修正が完了
    Steps:
      1. `git diff killer_7/report/sarif_export.py` で変更内容を確認
      2. diff に含まれるのが型注釈追加、`+` 演算子追加、`# pyright: ignore` コメントのみであること
      3. ロジック変更（条件分岐、リターン値、エラーメッセージの内容変更等）がないこと
    Expected Result: 型注釈/文字列結合/抑制コメントのみの変更
    Failure Indicators: if/else/return/raise のロジック変更が含まれる
    Evidence: .sisyphus/evidence/task-2-diff-review.txt
  ```

  **Evidence to Capture:**
  - [ ] task-2-sarif-warning-count.txt
  - [ ] task-2-sarif-test-result.txt
  - [ ] task-2-diff-review.txt

  **Commit**: YES (groups with Task 3)
  - Message: `chore(types): fix basedpyright warnings in sarif_export.py`
  - Files: `killer_7/report/sarif_export.py`
  - Pre-commit: `basedpyright killer_7/report/sarif_export.py && python3.11 -m unittest tests.test_sarif_export`

---

- [ ] 3. cli.py の priority warnings 解消（reportImplicitStringConcatenation + reportUnknown*）

  **What to do**:

  **A. `reportImplicitStringConcatenation` (26件)**
  cli.py全体に分布する隣接文字列リテラルに明示的な `+` 演算子を追加。
  対象行: L260, L1068, L1081, L1095, L1108, L1119, L1125, L1137, L1145, L1160, L1166, L1177, L1183, L1192, L1201, L1205, L1234, L1244, L1258, L1264, L1272, L1280, L1289, L1302, L1310, L1321, L1332
  全て `raise ValueError(...)` やログメッセージ内の隣接文字列。機械的修正。

  **B. `reportUnknownVariableType` + `reportUnknownArgumentType` (約13件＋connected warnings)**
  SARIF/review セクションに絞って対応:
  - L233, L237: `config.get()` の戻り値 → `schema_version: object = ...` 型注釈
  - L246: `for raw_name, raw_aspects in ...` → ループ変数型注釈
  - L270: `for raw_aspect in ...` → `raw_aspect: object`
  - L300: `default_preset_obj` → 型注釈追加
  - L514, L528: 関数の戻り値型が `dict[Unknown, Unknown]` → 戻り値型注釈追加
  - L676, L684, L689: aspects 関連の `.get()` 戻り値 → 型注釈
  - L889: `prev_no_sot_aspects_list` → 型注釈
  - L922: lambda 内の `a` → 型注釈
  - L1157, L1199, L1202, L1205: validate/manifest 関連 → 型注釈
  - L1625-1667: evidence/aspectsループ内の変数 → 型注釈
  - L1723-1780: findings/questions/updated_review等 → 型注釈
  - L1907-1913: aspects_list/entry/a/ok → 型注釈
  - L1976: lambda 内の `x` → 型注釈

  **型注釈のパターン**:
  - `.get()` の戻り値: `value: object = dict_obj.get("key")` または `value: str | None = ...`
  - ループ変数: `for item: object in collection:`（Python 3.12+）またはループ前に `item: object` を宣言
  - **重要**: Python 3.11 を使用中なので `for item: object in ...` 構文は使えない。代わりに:
    - ループ前に `item: object` を宣言
    - または `cast()` を使用
    - または変数への代入時に型注釈: `typed_item: object = item`

  **Must NOT do**:
  - `reportAny` / `reportExplicitAny` / `reportUnusedCallResult` の修正は Phase 1 対象外
  - `reportImplicitOverride` (2件) は Phase 1 対象外
  - cli.py の関数シグネチャやパブリックAPIの変更
  - argparse由来の Any プロパゲーションの修正（Phase 2）
  - `TypedDict` の導入

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: cli.py は2000+行の大規模ファイル。広範囲に散在する39+件のwarningを正確に修正する必要があり、周囲のコンテキストを理解して型注釈を選択する判断が必要。
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `tdd-protocol`: 既存テストの回帰確認のみ。新規テスト作成不要。

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 4
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `killer_7/cli.py:230-310` — config/preset パーシングセクション: Unknown型変数が多い
  - `killer_7/cli.py:510-530` — 戻り値型が `dict[Unknown, Unknown]` になる関数群
  - `killer_7/cli.py:670-695` — aspects関連の `.get()` チェーン
  - `killer_7/cli.py:1060-1340` — validate セクション: ImplicitStringConcatenation が集中
  - `killer_7/cli.py:1620-1670` — evidence/aspects ループ: Unknown型変数が多い
  - `killer_7/cli.py:1720-1780` — findings/review セクション: Unknown型変数が多い
  - `killer_7/cli.py:1900-1980` — summary/merge セクション: Unknown型変数が多い

  **WHY Each Reference Matters**:
  - 各セクションは warning が集中する範囲。エージェントはこれらの範囲を順番に修正する
  - validate セクション (L1060-1340) は ImplicitStringConcatenation が 26件中20+件集中するホットスポット

  **Acceptance Criteria**:
  - [ ] `basedpyright killer_7/cli.py 2>&1 | grep -c "reportImplicitStringConcatenation"` → `0`
  - [ ] `basedpyright killer_7/cli.py 2>&1 | grep -c "reportUnknownVariableType"` → `0` または大幅削減
  - [ ] `python3.11 -m unittest tests.test_cli -v 2>&1` → PASS (全テスト)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: cli.py の reportImplicitStringConcatenation ゼロ確認
    Tool: Bash
    Preconditions: Task 3 の全修正が完了
    Steps:
      1. `basedpyright killer_7/cli.py 2>&1 | grep -c "reportImplicitStringConcatenation"` を実行
      2. 結果が `0` であることを確認
    Expected Result: 0 (26件 → 0)
    Failure Indicators: カウント > 0
    Evidence: .sisyphus/evidence/task-3-cli-implicit-string-count.txt

  Scenario: cli.py の reportUnknownVariableType 削減確認
    Tool: Bash
    Preconditions: Task 3 の全修正が完了
    Steps:
      1. `basedpyright killer_7/cli.py 2>&1 | grep -c "reportUnknownVariableType"` を実行
      2. 結果が baseline（13）より小さいことを確認。目標: 0
    Expected Result: 0 または大幅削減 (13 → 0 が理想)
    Failure Indicators: baselineと同じかそれ以上
    Evidence: .sisyphus/evidence/task-3-cli-unknown-var-count.txt

  Scenario: cli.py のテスト回帰確認
    Tool: Bash
    Preconditions: Task 3 の全修正が完了
    Steps:
      1. `python3.11 -m unittest tests.test_cli -v 2>&1 | tail -5` を実行
      2. "OK" が含まれ、"FAILED" が含まれないことを確認
    Expected Result: 全テスト PASS
    Failure Indicators: "FAILED" または "ERROR" が存在
    Evidence: .sisyphus/evidence/task-3-cli-test-result.txt

  Scenario: cli.py のスコープ逾脱確認
    Tool: Bash
    Preconditions: Task 3 の全修正が完了
    Steps:
      1. `git diff killer_7/cli.py | grep "^+" | grep -v "^+++" | grep -v "^+.*: object" | grep -v "^+.*: str" | grep -v "^+.*: int" | grep -v "^+.*: list" | grep -v "^+.*: dict" | grep -v "^+.*+ f\"" | grep -v "^+.*+ \"" | grep -v "^+.*# pyright:"` を実行
      2. 型注釈/文字列結合/pyright ignore 以外の変更がないことを確認
    Expected Result: 型注釈と文字列結合演算子のみの変更
    Failure Indicators: ロジック変更行が検出される
    Evidence: .sisyphus/evidence/task-3-cli-scope-check.txt
  ```

  **Evidence to Capture:**
  - [ ] task-3-cli-implicit-string-count.txt
  - [ ] task-3-cli-unknown-var-count.txt
  - [ ] task-3-cli-test-result.txt
  - [ ] task-3-cli-scope-check.txt

  **Commit**: YES (groups with Task 2)
  - Message: `chore(types): fix basedpyright warnings in cli.py (Phase 1)`
  - Files: `killer_7/cli.py`
  - Pre-commit: `basedpyright killer_7/cli.py 2>&1 | grep -c "reportImplicitStringConcatenation" && python3.11 -m unittest tests.test_cli`

---

- [ ] 4. テスト検証 + ドキュメント更新 + AC4残課題記録

  **What to do**:
  - 全テストスイート実行: `python3.11 -m unittest discover -s tests -p 'test*.py'` → 264 tests PASS
  - テストファイルのwarning確認: Task 2/3 のソース変更に起因するテストファイルのwarningがあれば対応
  - Afterベースライン記録: Task 1 と同じ手順で変更後のwarning数を記録
    - `.sisyphus/evidence/task-4-after-baseline.json`
    - `.sisyphus/evidence/task-4-before-after-comparison.txt`
  - AC4 残課題ドキュメント: Issue #59 のコメントまたは別ファイルに以下を記載:
    - Phase 2 対象ファイルと優先順
    - `cli.py` の `reportAny` (61件) → `allowedUntypedLibraries` または `pyproject.toml` 設定で対応
    - `cli.py` の `reportUnusedCallResult` (21件) → 個別判断が必要
    - `cli.py` の `reportExplicitAny` (8件) → argparse型の改善が必要
    - `cli.py` の `reportImplicitOverride` (2件) → `override` デコレータ追加
    - テストファイルの `reportAny` (351件) → 大規模、別フェーズで対応
    - `pyproject.toml` への `[tool.basedpyright]` セクション追加の検討
  - docs/operations/sarif-reviewdog.md: 変更があれば更新（ソース変更の影響がなければスキップ）

  **Must NOT do**:
  - テストファイルの大規模な型注釈追加
  - Phase 2 の実装作業（ドキュメント化のみ）
  - pyproject.toml の変更

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: テスト実行、ベースライン記録、ドキュメント作成の単純なタスク群。
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential after Wave 2)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 2, Task 3

  **References**:

  **Pattern References**:
  - `.sisyphus/evidence/task-1-baseline.json` — Beforeベースライン（Task 1で作成済み）
  - `tests/test_sarif_export.py` — sarif_exportのテスト
  - `tests/test_cli.py` — cliのテスト
  - `docs/operations/sarif-reviewdog.md` — ドキュメント更新候補

  **WHY Each Reference Matters**:
  - Beforeベースラインと比較して削減数を算出するために Task 1 の証跡が必要
  - テストファイルはソース変更の影響を受ける可能性がある

  **Acceptance Criteria**:
  - [ ] `python3.11 -m unittest discover -s tests -p 'test*.py'` → 264 tests, 0 failures
  - [ ] `.sisyphus/evidence/task-4-before-after-comparison.txt` に Before/After のwarning数が記録
  - [ ] AC4 残課題ドキュメントが作成されている

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 全テストスイートの完全通過
    Tool: Bash
    Preconditions: Task 2, Task 3 が完了済み
    Steps:
      1. `python3.11 -m unittest discover -s tests -p 'test*.py' 2>&1 | tail -3` を実行
      2. "Ran 264 tests" と "OK" が含まれることを確認
      3. "FAILED" が含まれないことを確認
    Expected Result: 264 tests, 0 failures, 0 errors
    Failure Indicators: テスト数の変化、FAILED/ERRORの存在
    Evidence: .sisyphus/evidence/task-4-full-test-suite.txt

  Scenario: Before/After warning比較の完全性
    Tool: Bash
    Preconditions: Afterベースライン記録完了
    Steps:
      1. `cat .sisyphus/evidence/task-4-before-after-comparison.txt` を実行
      2. sarif_export.py: Before=14, After=0 が記載されていること
      3. cli.py: Before=219, After < 180 が記載されていること
      4. reportImplicitStringConcatenation: Before=30 (4+26), After=0 が記載
    Expected Result: 明確な削減が数値で確認できる
    Failure Indicators: After 数値が Before 以上、またはファイル不在
    Evidence: .sisyphus/evidence/task-4-before-after-comparison.txt

  Scenario: AC4 残課題ドキュメントの完全性
    Tool: Bash
    Preconditions: ドキュメント作成完了
    Steps:
      1. 残課題ドキュメントを確認
      2. 以下の最低限の項目が記載されていること:
         - Phase 2 対象ファイルリスト
         - 各warning種別の残件数
         - 推奨対応方針
    Expected Result: Phase 2 のロードマップが明確
    Failure Indicators: 対象ファイル/件数/方針が欠落
    Evidence: .sisyphus/evidence/task-4-ac4-doc-review.txt
  ```

  **Evidence to Capture:**
  - [ ] task-4-full-test-suite.txt
  - [ ] task-4-after-baseline.json
  - [ ] task-4-before-after-comparison.txt
  - [ ] task-4-ac4-doc-review.txt

  **Commit**: YES
  - Message: `docs: record LSP warning baseline and Phase 2 plan for issue-59`
  - Files: `.sisyphus/evidence/*`, AC4ドキュメント
  - Pre-commit: `python3.11 -m unittest discover -s tests -p 'test*.py'`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run basedpyright). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `basedpyright killer_7/report/sarif_export.py killer_7/cli.py` + `python3.11 -m unittest discover -s tests -p 'test*.py'`. Review all changed files for: unnecessary `# pyright: ignore`, `# type: ignore` without justification, behavioral changes disguised as type fixes, excessive/unnecessary type casts. Check git diff against baseline to confirm only type annotation + string concat operator changes.
  Output: `TypeCheck [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Run basedpyright on ALL target files. Compare warning counts Before vs After. Verify sarif_export.py = 0 warnings. Verify cli.py reportImplicitStringConcatenation = 0. Verify cli.py reportUnknown* reduced. Run full test suite from clean state. Save evidence.
  Output: `Scenarios [N/N pass] | Warning Reduction [before→after] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance — specifically: no reportAny fixes, no TypedDict additions, no pyproject.toml changes, no large-scale test file changes. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **T1**: No commit (setup only)
- **T2+T3**: `chore(types): fix basedpyright warnings in sarif_export and cli` — `killer_7/report/sarif_export.py`, `killer_7/cli.py`
- **T4**: `docs: record LSP warning baseline and Phase 2 plan for issue-59` — docs, tests (if changed)

---

## Success Criteria

### Verification Commands
```bash
# Warning check (sarif_export.py → 0 warnings expected)
basedpyright killer_7/report/sarif_export.py 2>&1 | grep -c "warning:"
# Expected: 0

# Warning check (cli.py → reduced from 219)
basedpyright killer_7/cli.py 2>&1 | grep -c "warning:"
# Expected: < 180

# Priority warnings eliminated (cli.py reportImplicitStringConcatenation → 0)
basedpyright killer_7/cli.py 2>&1 | grep -c "reportImplicitStringConcatenation"
# Expected: 0

# Full test suite
python3.11 -m unittest discover -s tests -p 'test*.py'
# Expected: 264 tests, 0 failures
```

### Final Checklist
- [ ] AC1: ベースライン（Before/After warning数）記録済み
- [ ] AC2: sarif_export.py 14→0, cli.py reportImplicitStringConcatenation 26→0, cli.py reportUnknown* 削減
- [ ] AC3: 264 tests all passing
- [ ] AC4: Phase 2 分割方針ドキュメント作成済み
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
