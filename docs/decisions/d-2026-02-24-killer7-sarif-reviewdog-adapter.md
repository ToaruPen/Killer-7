# Decision: Killer-7 に SARIF/reviewdog 連携アダプタを段階導入する

## Decision-ID

D-2026-02-24-KILLER7_SARIF_REVIEWDOG_ADAPTER

## Context

- 背景: Issue #52 で、Killer-7 の既存品質ゲートを維持したまま、PR 上の行位置提示と CI 連携の標準化を強化する要件が確定した。
- どの矛盾/制約を解決するか: 既存の native inline 投稿だけでは外部ツール連携の再利用性が低く、運用チャネルを拡張しにくい。全面置換はリスクが高いため、既存コアを維持して adapter 追加で解決する。

## Rationale

- なぜこの決定を採用したか:
  - `review-summary.json` を SARIF 2.1.0 に変換することで、標準フォーマット経由の可搬性を確保できるため。
  - reviewdog をオプション連携に限定し、既存の native inline フローを既定挙動として保持できるため。
  - stale head 検知時に fail-fast で成果物をクリアし、古い成果物参照を防止できるため。
- SoT（PRD/Epic/Issue）との整合:
  - PRD の品質契約（schema/evidence/inline fail-fast）を維持しつつ拡張する方針に一致。
  - Epic の K7-18（Issue #52）に定義された導入方針と一致。

## Alternatives

### Alternative-A: 既存 native inline を SARIF/reviewdog で全面置換する

- 採用可否: No
- Pros:
  - 実装経路を 1 本化できる。
- Cons:
  - 既存の安定経路を一括置換するため、回帰リスクと切り戻しコストが高い。

### Alternative-B: 既存実装のまま SARIF/reviewdog を導入しない

- 採用可否: No
- Pros:
  - 追加実装が不要。
- Cons:
  - 標準フォーマット連携と annotation 経路の拡張性を得られない。

## Impact

- 影響範囲:
  - `killer_7/cli.py`（`--sarif` / `--reviewdog` / stale 成果物制御）
  - `killer_7/report/sarif_export.py`（SARIF 変換）
  - `killer_7/github/reviewdog.py`（reviewdog 実行）
  - `killer_7/artifacts.py`（SARIF 成果物書き込み）
  - `docs/operations/sarif-reviewdog.md`（運用手順）
- 互換性:
  - 既存 `--post` / `--inline` の既定挙動は維持。
  - SARIF/reviewdog は明示指定時のみ有効。
- 運用影響:
  - CI/ローカルで SARIF 成果物を再利用可能。
  - reviewdog 失敗時は明示エラーで停止し、失敗原因を追跡しやすい。

## Verification

- 検証方法:
  - `python3 -m unittest discover -s tests -p 'test*.py'`
  - `python3 -m ruff check scripts killer_7`
  - `python3 -m ruff format --check scripts killer_7`
  - `python3 -m mypy scripts`
  - `python3 scripts/lint-sot.py docs`
  - `GH_ISSUE=52 DIFF_MODE=worktree TEST_COMMAND="python3 -m unittest discover -s tests -p 'test*.py'" bash scripts/review-cycle.sh issue-52`
- エビデンス:
  - `tests/test_sarif_export.py` と `tests/test_reviewdog.py` で新規経路を検証。
  - `.agentic-sdd/reviews/issue-52/20260224_082505/review.json` で最終 `Approved` を確認。

## Supersedes

- N/A

## Inputs Fingerprint

- PRD: `docs/prd/killer-7.md`
- Epic: `docs/epics/killer-7-epic.md`
- Issue: `https://github.com/ToaruPen/Killer-7/issues/52`
- Related files:
  - `killer_7/cli.py`
  - `killer_7/report/sarif_export.py`
  - `killer_7/github/reviewdog.py`
  - `killer_7/artifacts.py`
  - `docs/operations/sarif-reviewdog.md`
