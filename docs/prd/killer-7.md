# PRD: Killer-7

> このテンプレートは `/create-prd` コマンドで使用されます。
> 各セクションを埋めて、完成チェックリストをすべて満たしてください。

---

## メタ情報

- 作成日: 2026-02-05
- 作成者: @toarupen
- ステータス: Approved
- バージョン: 1.0

---

## 1. 目的・背景

開発で利用するLLMのquota消費を抑えつつ、LLM由来のコード劣化とプロジェクト破綻を防ぐため、複数観点の自動PRレビューを標準化する。低コストで回せる複数レビュワーと機械検証（schema/evidence）により、レビューの品質と再現性を担保する。

---

## 2. 7つの質問への回答

### Q1: 解決したい問題は？

開発に使用しているAIのquota使用量を削減しつつ、LLMの性質から生じるコード品質の劣化やプロジェクトの破綻リスクを抑えたい。性能はやや劣るが数を回せるAIを用意し、観点別レビューで問題点の発見率を上げ、開発サイドのAIが少ないquotaで改善に集中できる状態にする。

### Q2: 誰が使う？

- 主ユーザー: 私個人（メイン）
- 想定する拡張ユーザー: 他の開発者も利用できる形で、Dockerコンテナのフレームワークとして提供する（ローカル実行/自前runnerでのGitHub Actions運用のどちらでも使える）
- 利用形態: 開発PCとは別のPC上にKiller-7を配置し、GitHub上のPRを入力としてレビューを実行し、結果をPRへ投稿する

### Q3: 何ができるようになる？

- PRを入力として、7つの観点（Correctness/Readability/Testing/Test Audit/Security/Performance/Refactoring）の自動レビューを実行できる
- diffとSoT（Source of Truth）を中心に、Context Bundleを生成してレビュワーへ渡し、根拠に基づく指摘のみを出力させられる
- レビュー出力（JSON）をスキーマ検証し、evidence検証により根拠不明な強い指摘（P0/P1等）が残らないように抑制できる

注記（スキーマ運用）:

- スキーマは原則として厳格（unknown field禁止）とし、フィールド拡張はスキーマ更新を伴う
- 結果をPRコメント（要約）として投稿でき、P0/P1のみをinlineコメントとして投稿できる（冪等更新、重複排除）
- 成果物（レポート/ログ/バンドル）をローカルの `.ai-review/` 配下に保存でき、終了コードでゲートできる（例: Blocked=1、実行失敗=2）

LLM実行方式:

- レビュワーLLMの実行にはopencodeを組み込み、ヘッドレスで実行する
- LLMプロバイダの認証はユーザーが事前に行う（Killer-7が認証フローを実装しない）。Killer-7は認証済みのプロバイダ/モデルを利用できる

想定コマンド例（ローカルCLI; 実体はDockerで実行）:

```bash
# PR番号を入力にしてレビュー（投稿なし）
killer-7 review --repo owner/name --pr 123

# 要約コメント投稿
killer-7 review --repo owner/name --pr 123 --post

# 要約 + inline（P0/P1）投稿
killer-7 review --repo owner/name --pr 123 --post --inline
```

ハイブリッド方針:

- デフォルト: diff + Context Bundle + allowlistで指定したSoTのみをレビュワーに提供する
- 追加: 特定観点のみリポジトリ内容へread-onlyアクセスを許可できる（allowlistでパス制限）
- 不足情報は questions として回収し、追加の抜粋生成または対象観点のみ再実行で吸収する

探索モード（作業ツリー探索 + 証跡）:

- `--explore` 指定時、OpenCode に repo 探索（read/grep/glob + bash/git）を許可し、差分外の周辺文脈を確認できる
- 探索の証跡（tool_use）を `.ai-review/` に保存し、必要に応じて監査・機械検証できる
- bash は読み取り専用の git コマンドに限定し、許可外コマンド/必須フラグ欠落は Blocked（終了コード 1）とする
- read は git 管理ファイルに限定し、`.git/` や `.env` など機微領域の読み取りは拒否する
- grep/glob は範囲が広くなりがちなので、探索モードでは対象を絞る（例: `include`/`pattern` は拡張子を含むこと、`.env` を含む可能性がある指定は拒否する）
- ポリシー適用は tool trace（OpenCodeのJSONLイベント）を事後検証して行う（違反は Blocked）。OpenCode 側の実行経路を完全にサンドボックス化するものではない
- evidence 検証は (Context Bundle + SoT + tool bundle) を対象にし、探索に基づく sources でも unverified 扱いにならないようにする
- tool bundle は証跡として (path + line numbers) を保存し、ファイル内容は永続化しない

### Q4: 完成と言える状態は？

- GitHub上の任意のPRに対して、同一のCLI操作でレビューを実行できる
- 7観点レビューが走り、集約された `review-summary.json` と `review-summary.md` が生成される
- `review-summary.json` が固定スキーマに合格し、evidence検証が有効な場合に根拠不明なP0/P1が最終結果に残らない
- `--post` 指定で要約コメントがPR上で冪等更新され、`--inline` 指定でP0/P1がinline投稿される（重複しない）
- `--inline` 指定時にP0/P1が150件を超える場合、inline投稿は行わず要約へ退避し、終了コードはBlocked（1）となる（要約コメントは更新される）
- APIキー未設定やモデル応答不正などの失敗が、終了コードとログで判別できる

### Q5: 作らない範囲は？

- コードの自動修正（レビュー結果に基づく自動コミット、PR自動作成、強制リライト）
- self-hosted runnerの管理（Killer-7はrunner上で実行できるが、runnerの導入/管理/運用は提供しない）
- 常時稼働のインデックス/RAGサーバー（ベクトルDBの常駐など）
- 静的解析ツール（lint/typecheck/security scan/test）で確定的に検出できる事項の重複報告

### Q6: 技術的制約は？

Q6-1: 既存言語/フレームワーク固定
選択: Yes
詳細（Yesの場合）: Dockerを前提とし、実装はPython + Bashを中心とする

Q6-2: デプロイ先固定
選択: Yes
詳細（Yesの場合）: ローカル（別PCを含む）で実行するCLI。入力はGitHub PR（`gh`/GitHub API）。GitHub Actions（共有self-hosted runner）上での運用も想定するが、Killer-7がCI基盤/runnerを管理しない

Q6-3: 期限
選択: Unknown
詳細（日付の場合）: -

Q6-4: 予算上限
選択: ある
詳細（あるの場合）: 低コストモデルを基本とし、入力コンテキストをバンドル化して送信量を上限制御する

Q6-5: 個人情報/機密データ
選択: Yes
詳細（Yesの場合）: リポジトリ内容は機密として扱い、送信するコンテキストは最小化する。ログに秘密情報（API key等）や不要なファイル内容を出力しない

補足（GitHub Actions運用）:

- 共有self-hosted runner上でGitHub Actionsとして運用する場合、fork PRはデフォルトで実行対象外とする（secrets保護）
- その場合も結果はPRコメント（要約 + P0/P1 inline）で可視化するが、レビューの強制力（マージのブロック）は運用側で選べる（デフォルトはadvisory）

Q6-6: 監査ログ要件
選択: No
詳細（Yesの場合）: -

Q6-7: パフォーマンス要件
選択: Yes
詳細（Yesの場合）:
  - 対象操作: 1PRレビュー実行（7観点並列を含む）
  - 目標概要:
    - 1回の実行時間: 20分以内（Killer-7側でタイムアウトを設定する）
    - 送信コンテキスト上限: Context Bundle 最大1500行、1ファイル最大400行、SoT合計最大250行（上限を超える場合は切り詰めと警告を出す）
    - PR投稿（inline含む）: P0/P1 inlineは最大150件（超過時は要約へ退避し、終了コードはBlocked=1。要約コメントは更新される）

Q6-8: 可用性要件
選択: No
詳細（Yesの場合）: -

### Q7: 成功指標（測り方）は？

指標-1
指標: 1PRあたりのレビューコスト（トークン/リクエスト数）
目標値:
- LLM呼び出し回数: 1回のレビュー実行あたり最大8回（7観点 + 集約1回）
- 送信コンテキスト上限: Context Bundle最大1500行、SoT合計最大250行を超えない
測定方法: 実行ログ/成果物に、観点ごとの呼び出し回数、Context Bundle/SoTの行数、合計を保存する

指標-2
指標: 品質ゲートとしての有効性（強い指摘の信頼性）
目標値: evidence検証が有効な場合、最終結果のP0/P1はすべて `verified=true` となる（`verified=false` のP0/P1を0件にする）
測定方法: `validate-evidence` の統計（verified/unverified/downgraded）と、最終レポートのP0/P1の `verified` を照合する

---

## 3. ユーザーストーリー

### US-1: PRを自動レビューして投稿したい

```text
As a ソロ開発者,
I want to GitHub PRを入力として多観点の自動レビューを実行し、要約とP0/P1のinline指摘をPRへ投稿したい,
So that quota消費を抑えながら品質を維持できる.
```

### US-2: 開発PCと分離した環境で運用したい

```text
As a 開発者,
I want to 開発PCとは別のPC上でレビューを実行したい,
So that ローカル環境差分の影響を減らし、レビュー基盤を安定運用できる.
```

---

## 4. 機能要件

FR-1
機能名: PR入力（diff取得）
説明: PR番号/URLからdiffと変更メタデータ（変更ファイル一覧、head sha等）を取得できる
優先度: Must

FR-2
機能名: Context Bundle生成
説明: diffから右側（HEAD）の抜粋を生成し、`# SRC:`ヘッダで根拠を固定できる。上限制御（総行数/ファイル行数/SoT行数）を持つ
優先度: Must

FR-3
機能名: SoT収集（allowlist）
説明: 指定したパスallowlist（glob）に一致するSoTファイルを収集してバンドルへ含める
優先度: Must

FR-4
機能名: 7観点レビュー実行
説明: 7観点を並列に実行し、各観点のJSON出力を得る
優先度: Must

FR-5
機能名: 出力スキーマ検証
説明: 生成されたレビューJSONが固定スキーマに合格することを検証し、不正な出力を失敗として扱う
優先度: Must

FR-6
機能名: evidence検証とポリシー適用
説明: `sources`/`code_location` がContext Bundleと整合しない指摘を検出し、強い指摘（P0/P1/P2）を格下げまたは除外する
優先度: Must

FR-7
機能名: PR投稿（要約/inline）
説明: `--post` で要約コメントを冪等更新し、`--inline` でP0/P1のみをinlineコメントとして冪等投稿する
優先度: Should

---

## 5. 受け入れ条件（AC）

### 正常系

- [ ] AC-1: `killer-7 review --repo <owner/name> --pr <number>` を実行すると、`review-summary.json` と `review-summary.md` が生成される
- [ ] AC-1a: 成果物はデフォルトで `./.ai-review/` 配下に生成される（例: `./.ai-review/review-summary.json`）
- [ ] AC-2: `review-summary.json` が固定スキーマに合格する
- [ ] AC-3: evidence検証が有効な場合、根拠不明なP0/P1が最終結果に残らない（格下げ/除外される）
- [ ] AC-4: `--post` 指定でPRの要約コメントが冪等更新される（同一PRでコメントが増殖しない）
- [ ] AC-5: `--inline` 指定でP0/P1のみがinline投稿され、再実行しても重複しない
- [ ] AC-6: `--inline` 指定時にP0/P1が151件以上の場合、inline投稿は行わず要約へ退避し、終了コードがBlocked（1）になる（要約コメントは冪等更新される）
- [ ] AC-6a: `--inline` 指定時に、evidence検証/ポリシー適用後の最終 findings が P0/P1 のまま残っているにも関わらず（downgrade により P3 になったものは対象外）、`code_location` が diff(right/new side) にマップできない場合、inline投稿は行わず終了コードがBlocked（1）になる（要約コメントは冪等更新される）
- [ ] AC-7: `--explore` 指定時、tool trace と tool bundle が `.ai-review/` に保存される（例: `tool-trace.jsonl`, `tool-bundle.txt`, `opencode/*/stdout.jsonl`。stdoutはtool_useイベントのみで、output等を除去したredacted JSONL）
- [ ] AC-8: `--explore` 指定時、bashの許可リスト外コマンドが実行された場合、レビューは Blocked（1）で失敗する
- [ ] AC-9: `--explore` 指定時、探索に基づく findings の sources が evidence検証に通り、P0/P1 が不当に downgrade されない

### 異常系（必須: 最低1つ）

- [ ] AC-E1: APIキー未設定、またはモデル応答が不正JSONの場合、終了コードが0以外となり、原因がログで判別できる（成果物ディレクトリに失敗情報が残る）

---

## 6. 非機能要件（該当する場合）

- セキュリティ: 送信コンテキストはdiff/バンドル/SoTに限定し、repo全文アクセスはread-onlyかつ観点/パスallowlistで制限できる
- 運用: 実行ログと成果物をローカルに保存し、後から比較・検証できる
- その他: すべての出力は機械処理（JSON）と人間閲覧（Markdown）の両方を提供する

---

## 7. 規模感と技術方針

- 規模感: 個人
- 技術方針: シンプル優先（ただし根拠検証と冪等投稿は必須）
- 依存/OSS方針: 「数を入れないこと」自体が目的ではなく、LLMが推測で勝手に依存やコンポーネントを追加する行為を禁止する
- 依存/OSSの採用条件: 次のいずれかを満たす場合は積極的に採用する（採用理由をEpic/Issueに明記する）
  - 必須（正確性/安全性/仕様達成のために不可欠）
  - 工数が明確に減り、確実性が上がる
  - 利用者が多く著名で、保守されているOSSである

---

## 8. 用語集

用語-1
用語: SoT（Source of Truth）
定義: 要件・設計・運用ルールとして、レビュー時に参照すべき一次情報（PRD/Epic/決定記録など）

用語-2
用語: Context Bundle
定義: diffから生成した右側（HEAD）の抜粋とSoTを、`# SRC:`ヘッダ付きでまとめたレビュー用コンテキスト

用語-3
用語: evidence検証
定義: レビュー指摘の `sources` と `code_location` がContext Bundleにより裏付けられるかを機械的に検証する処理

---

## 完成チェックリスト

- [x] 目的・背景が1-3文で書かれている
- [x] ユーザーストーリーが1つ以上ある
- [x] 機能要件が3つ以上列挙されている
- [x] ACが検証可能な形式で3つ以上ある
- [x] ACに異常系（エラー/権限不足/入力不正）が最低1つある
- [x] スコープ外が明記されている
- [x] 曖昧な表現がない（禁止語辞書参照）
- [x] 数値・条件が具体的
- [x] 成功指標が測定可能な形式で書かれている
- [x] Q6のUnknownが2つ未満である

---

## 変更履歴

- 2026-02-05: v1.0 初版作成（@toarupen）
