# Decision: Killer-7 配布更新をタグ基準の stable/canary に統一する

## Decision-ID

D-2026-02-22-KILLER7_TAG_CHANNEL_AUTO_UPDATE

## Context

- 背景: Issue #49 で、管理PCへ配布済みの Killer-7 を自動更新する運用要件が追加された。
- どの矛盾/制約を解決するか: `main` 追従更新だと未検証変更が混入し得るため、リリースタグ基準へ固定して安定配布と先行検証（canary）を両立する。

## Rationale

- なぜこの決定を採用したか:
  - 配布更新の基準をリリースタグに固定することで、配布物と履歴（Release/タグ）を一致させ、事故調査を容易にするため。
  - canary をプレリリースタグに限定し、stable への影響を分離するため。
  - 更新後ヘルスチェック失敗時にロールバックを必須化し、運用上の復旧時間を短縮するため。
- SoT（PRD/Epic/Issue）との整合:
  - PRD の機能要件に FR-9/FR-10、受け入れ条件に AC-13〜AC-16 を追加し整合。
  - Epic に K7-17（Issue #49）と Phase-4 を追加し、実装スコープを明示。

## Alternatives

### Alternative-A: `main` ブランチ先頭を常時追従する

- 採用可否: No
- Pros:
  - 更新検知が単純。
- Cons:
  - 未リリース変更が配布環境へ流入し、再現性と安全性が低下する。

### Alternative-B: stable のみ運用し canary を持たない

- 採用可否: No
- Pros:
  - 運用ルールが単純になる。
- Cons:
  - 先行検証チャネルがなく、正式リリース前の段階的検証が難しい。

## Impact

- 影響範囲:
  - 配布更新スクリプト（`scripts/killer-7-update.sh`）
  - リリースワークフロー（`.github/workflows/release.yml`）
  - 運用手順（`docs/operations/killer-7-update.md`）
  - SoT（`docs/prd/killer-7.md`, `docs/epics/killer-7-epic.md`）
- 互換性:
  - 既存の `killer-7 review` CLI の挙動は不変。
  - 配布運用はタグ基準へ明示化される。
- 運用影響:
  - stable/canary のチャネル選択が可能になる。
  - ヘルスチェック失敗時は自動ロールバック、ロールバック失敗は致命エラーとして通知される。

## Verification

- 検証方法:
  - `bash scripts/tests/test-killer7-update.sh`
  - `python3 -m ruff check scripts`
  - `python3 -m ruff format --check scripts`
  - `python3 -m mypy scripts`
- エビデンス:
  - `scripts/killer-7-update.sh` で `sh -lc` によるヘルスチェック実行とロールバック失敗の明示エラー化を確認。
  - `scripts/tests/test-killer7-update.sh` でコマンド実行形式とロールバック失敗ケースの回帰テストを追加。

## Supersedes

- N/A

## Inputs Fingerprint

- PRD: `docs/prd/killer-7.md`
- Epic: `docs/epics/killer-7-epic.md`
- Issue: `https://github.com/ToaruPen/Killer-7/issues/49`
- Related files:
  - `scripts/killer-7-update.sh`
  - `scripts/tests/test-killer7-update.sh`
  - `.github/workflows/release.yml`
  - `docs/operations/killer-7-update.md`
