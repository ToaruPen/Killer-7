# Full見積もり

## 0. 前提確認

- Issue: #80 fix: explore パイプラインのエラーハンドリング不備3件（ValueError漏れ・OSError未捕捉・サイレントフォールバック）
- Epic: N/A（既存コードのバグ修正）
- PRD: N/A（既存コードのバグ修正）
- 技術方針: シンプル優先
- 設定値/定数の方針: 既存の定数・設定をそのまま使用

## 1. 依頼内容の解釈

PR #79 の CodeRabbit レビューで指摘された explore パイプラインのエラーハンドリング不備3件を修正する。いずれも `killer_7/llm/opencode_runner.py` 内のエッジケース。エラー原因のマスキングや設定ミス未検知を防止する。

## 2. 変更対象（ファイル:行）

Change-1
file: `killer_7/llm/opencode_runner.py`
change: `_expand_brace_glob_once` — `p.index` を `p.find` に変更し、`}` が `{` より前にある不正パターンで `_explore_policy_violation` を呼び出す
loc_range: 5-8行

Change-2
file: `killer_7/llm/opencode_runner.py`
change: `_handle_subprocess_timeout` — `_read_file_truncated()` を try/except OSError で囲み、失敗時はプレースホルダ文字列を使用
loc_range: 8-12行

Change-3
file: `killer_7/llm/opencode_runner.py`
change: `KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES` パース — `except ValueError: pass` を `raise ExecFailureError(...)` に変更
loc_range: 3-5行

Change-4
file: `tests/` 内の該当テストファイル
change: 3件のACに対するユニットテスト追加
loc_range: 30-60行

total_loc_range: 46-85行

## 3. 作業項目と工数（レンジ + 信頼度）

Task-1
task: AC1 — `_expand_brace_glob_once` ValueError漏れ修正
effort_range: 0.2-0.5h
confidence: High

Task-2
task: AC2 — `_handle_subprocess_timeout` OSError捕捉追加
effort_range: 0.2-0.5h
confidence: High

Task-3
task: AC3 — `KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES` サイレントフォールバック修正
effort_range: 0.1-0.3h
confidence: High

Task-4
task: テスト作成・実行
effort_range: 0.5-1h
confidence: High

Task-5
task: 品質チェック（ruff/mypy/既存テスト全通し）
effort_range: 0.2-0.5h
confidence: High

total_effort_range: 1.2-2.8h
overall_confidence: High

## 4. DB影響

N/A（DB操作なし。内部エラーハンドリングのみ）

## 5. ログ出力

N/A（ログ変更なし。既存のエラーメッセージ改善のみ）

## 6. I/O一覧

N/A（外部I/Oなし。内部処理のみ）

## 7. リファクタ候補

N/A（今回はバグ修正のみ。`_env_int()` も同様のサイレントフォールバックパターンだが、スコープ外）

## 8. フェーズ分割

N/A（単一フェーズで完了可能。推定85行以下）

## 9. テスト計画

Test-1
kind: Unit
target: `_expand_brace_glob_once` (AC1)
content: `}` が `{` より前にあるパターンを渡して `BlockedError` が発生すること

Test-2
kind: Unit
target: `_handle_subprocess_timeout` (AC2)
content: 存在しないstdout_pathを渡しても `error.json` が正常に書き込まれること

Test-3
kind: Unit
target: `_explore_validate_and_trace` 内の env 変数パース (AC3)
content: `KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES="abc"` を設定して `ExecFailureError` が発生すること

## 10. 矛盾点/不明点/確認事項

なし

## 11. 変更しないこと

- `_env_int()` のサイレントフォールバックパターン（スコープ外）
- `_persist_stdio_for_failure` のエラーハンドリング（AC2は `_handle_subprocess_timeout` のみ対象）
- `killer_7/explore/policy.py`（AC1の対象は `opencode_runner.py` 内の `_expand_brace_glob_once`）
