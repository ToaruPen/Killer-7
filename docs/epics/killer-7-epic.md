# Epic: Killer-7（自動PRレビュー基盤 v1）

> このテンプレートは `/create-epic` コマンドで使用されます。
> PRDを参照し、実装計画を作成してください。

---

## メタ情報

- 作成日: 2026-02-05
- 作成者: @toarupen
- ステータス: Draft
- 参照PRD: `docs/prd/killer-7.md`

---

## 1. 概要

### 1.1 目的

LLMのquota消費を抑えつつ、LLM由来のコード劣化とプロジェクト破綻を防ぐため、複数観点の自動PRレビュー（要約コメント/inlineコメント投稿を含む）をCLIとして提供する。diff + Context Bundle + SoT allowlistを軸に、schema/evidenceの機械検証で“根拠のない強い指摘”を排除し、再現性のある品質ゲートを作る。

### 1.2 スコープ

**含む:**
- GitHub PRを入力とするレビュー実行（差分取得、変更メタデータ取得）
- Context Bundle生成（右側/HEAD中心、上限制御あり）
- SoT収集（allowlist; PRブランチ上の指定パスを収集）
- 7観点レビュー実行（Correctness/Readability/Testing/Test Audit/Security/Performance/Refactoring）
- 出力JSONのschema検証、evidence検証とポリシー適用（格下げ/除外）
- 生成成果物の保存（`.ai-review/`）
- PRへの要約コメント投稿（冪等更新）
- P0/P1のinlineコメント投稿（冪等、上限150）
- ハイブリッド運用（通常はdiff+bundle+SoT、必要時のみrepo read-only + allowlist）
- 探索モード（`--explore`）: repo探索（read/grep/glob + bash/git）を許可し、tool trace / tool bundle を保存する。bashは読み取り専用gitに制限し（許可外はBlocked）、readはgit管理ファイルに限定する。grep/globは対象を絞る（例: 拡張子を含む `include`/`pattern` を必須にし、`.env` 等を対象にし得る指定は拒否）。tool bundleは (path + line numbers) のみを保存する
- 探索モードのポリシー適用は tool trace（OpenCodeのJSONLイベント）を事後検証して行う（違反は Blocked）。OpenCode の実行経路を完全にサンドボックス化するものではない
- `--inline` のfail-fast: P0/P1 findings が diff(right/new side) にマップできない場合は Blocked として扱う

**含まない（PRDのスコープ外を継承）:**
- レビュー結果に基づくコード自動修正（自動コミット/PR自動作成）
- self-hosted runnerの管理
- 常時稼働のRAG/インデックスサーバー（ベクトルDB常駐など）
- 静的解析（lint/typecheck/security scan/test）で確定的に検出できる事項の重複報告

### 1.3 PRD制約の確認

項目: 規模感
PRDの値: 個人
Epic対応: 単一CLI（単一コンテナプロセス）を基本にし、機能を最小構成で積み上げる

項目: 技術方針
PRDの値: シンプル優先
Epic対応: 外部サービス/新規コンポーネントを最小にし、非同期基盤/マイクロサービス/K8sを採用しない

依存/OSSの運用方針:

- 目的は「依存数をゼロにする」ではなく、LLMが推測で勝手に依存やコンポーネントを追加する行為を禁止すること
- 新規依存の追加は、採用理由（必須/工数削減+確実性/著名OSS）をIssueと見積もりに明記した場合のみ許可する

項目: 既存言語/FW
PRDの値: Yes
Epic対応: Docker前提、実装はPython + Bash中心

項目: デプロイ先
PRDの値: Yes
Epic対応: ローカル（別PC含む）で実行するCLI。入力はGitHub PR（`gh`/GitHub API）

項目: 期限
PRDの値: Unknown（解消）
Epic対応: 期限なし（段階リリース）

---

## 2. 必須提出物（3一覧）

> **注意**: この3つの一覧は必須です。空欄にせず、該当なしの場合は「なし」と明記。

### 2.1 外部サービス一覧

外部サービス-1
名称: GitHub API（gh経由）
用途: PR差分/メタデータ取得、要約/inlineコメント投稿
必須理由: 入力がGitHub PRであり、出力先もPRコメントであるため
代替案: （よりシンプル）投稿機能を廃止し、ローカル成果物のみ出力（ただしPRDで投稿を含むため不採用）

外部サービス-2
名称: LLM API（opencodeが利用するプロバイダ）
用途: 7観点レビューの生成
必須理由: 自動レビューのコア機能
代替案: （よりシンプル）単一モデル/単一観点レビュー（ただしPRDで7観点を要求するため不採用）

注記: 技術方針「シンプル優先」の外部サービス上限（1）を超過するが、PRDの必須要件（GitHub PR入力 + LLMレビュー）により例外として採用する。

### 2.2 コンポーネント一覧

コンポーネント-1
名称: Killer-7 CLI（コンテナ）
責務: PR入力→差分取得→バンドル生成→7観点レビュー実行→検証/集約→成果物保存→（任意）PR投稿
デプロイ形態: ローカルDocker（単一コンテナプロセス）

コンポーネント-2
名称: なし
責務: -
デプロイ形態: -

### 2.3 新規技術一覧

新規技術-1
名称: Docker
カテゴリ: コンテナ実行
既存との差: 新規導入
導入理由: 別PC運用と配布性、依存の固定

新規技術-2
名称: Python 3.11
カテゴリ: 言語/ランタイム
既存との差: 新規導入
導入理由: スクリプト群（バンドル生成、検証、集約、GitHub投稿）を依存少なく実装

新規技術-3
名称: opencode（headless）
カテゴリ: LLM実行
既存との差: 新規導入
導入理由: ユーザーが認証済みのプロバイダ/モデルを利用でき、Killer-7側で認証フローを持たずに運用できる

新規技術-4
名称: GitHub CLI（gh）
カテゴリ: 外部APIクライアント
既存との差: 新規導入
導入理由: PR diff取得と投稿を安定的に行う（API生呼びの実装量を抑える）

---

## 3. 技術設計

### 3.1 アーキテクチャ概要

システム境界:

- Killer-7は「入力=GitHub PR」「出力=ローカル成果物 +（任意）PRコメント投稿」を行うローカルCLIである
- Killer-7はGitHub Actions（共有self-hosted runner）上で実行できるが、runnerの導入/管理はスコープ外とする
- GitHub Actions運用時はfork PRをデフォルトで実行対象外とし（secrets保護）、結果はPRコメント（要約+P0/P1 inline）として掲示する（ただしinlineは上限超過時に抑制）
- LLMには最小化したコンテキスト（diff + Context Bundle + SoT allowlist）を送る
- repo全文へのアクセスはデフォルト無効（ハイブリッド）。必要時のみread-onlyかつパスallowlistで制限する
- 探索モード（`--explore`）では、OpenCodeのrepo探索を許可する代わりに、tool trace/bundle を成果物として保存し、後段のevidence検証で探索由来の根拠も検証対象に含める（readはgit管理ファイルに限定し、bundleは内容を永続化しない）
- `--inline` 実行時は、P0/P1 findings の `code_location` が diff にマップできない場合は品質ゲートとして Blocked にする（黙ってスキップしない）

主要データフロー-1
from: ユーザー（CLI起動）
to: Killer-7 CLI
用途: 対象PRの指定（owner/name + PR番号）と実行オプション（投稿/inline/ハイブリッド）
プロトコル: CLI

主要データフロー-2
from: Killer-7 CLI
to: GitHub API（gh）
用途: PR diff、変更ファイル一覧、head sha、投稿（issue comment / review comment）
プロトコル: HTTPS

主要データフロー-3
from: Killer-7 CLI
to: opencode（headless）
用途: 7観点レビュー生成（JSON schema v3）
プロトコル: ローカルプロセス（opencodeがHTTPSで外部APIへ接続）

主要データフロー-4
from: Killer-7 CLI
to: ローカル成果物（`.ai-review/`）
用途: バンドル、レビューJSON、集約レポート、検証統計、実行ログの保存
プロトコル: ファイルI/O

### 3.2 技術選定

技術選定-1
カテゴリ: 実行形態
選択: ローカルCLI（Dockerで実行）
理由: どのrepoにも適用しやすく、別PC運用が可能で、GitHub Actionより環境差分/権限問題を単純化できる
代替案（よりシンプル）: ホストに直接インストール（pip）
不採用理由: 依存と環境差分が増え、配布性と再現性が落ちる

技術選定-2
カテゴリ: GitHub連携
選択: `gh` + GitHub API
理由: PR diff取得/コメント投稿を少ない実装量で安定させる
代替案（よりシンプル）: GitHub APIをHTTPで直叩き
不採用理由: 認証/ページング/投稿の細部実装が増える

技術選定-3
カテゴリ: LLM呼び出し
選択: opencode（headless）
理由: ユーザーが認証済みのプロバイダ/モデルを利用でき、Killer-7が認証フローやプロバイダ個別実装を抱えずに済む
代替案（よりシンプル）: OpenAI互換APIを直接呼び出す
不採用理由: プロバイダ差し替え/認証方式の違いをKiller-7側で吸収する必要が増える

技術選定-4
カテゴリ: レビューの根拠制御
選択: Context Bundle（右側/HEAD中心）+ schema/evidence検証
理由: LLMの捏造や過剰指摘を機械的に抑制し、品質ゲートを成立させる
代替案（よりシンプル）: diff全文をそのまま投入
不採用理由: トークン量が増え、根拠の整合性を機械検証できない

技術選定-5
カテゴリ: 言語
選択: Python 3.11
理由: バンドル生成/検証/集約/投稿を、依存を増やさず実装できる
代替案（よりシンプル）: Bashのみ
不採用理由: JSON検証や冪等投稿の実装が複雑化しやすい

技術選定-6
カテゴリ: インフラ
選択: Docker
理由: 別PC運用と配布性、依存の固定を実現する
代替案（よりシンプル）: ホストに直接インストール（pip）
不採用理由: 環境差分が増え、再現性が落ちる

### 3.3 データモデル（概要）

エンティティ-1
名前: ReviewSummary
主要属性: schema_version, status, aspect_statuses, findings[], questions[], overall_explanation
関連: findingsはFinding[]

注記:

- `aspect_statuses` は集約レポート（`review-summary.json`）で付与される想定。観点別JSON（`.ai-review/aspects/*.json`）には含まれない場合がある
- スキーマは原則として厳格（unknown field禁止）とし、フィールド拡張はスキーマ更新を伴う

エンティティ-2
名前: Finding
主要属性: title, body, priority(P0-P3), sources, code_location, verified, original_priority
関連: code_locationは( repo_relative_path, line_range )

### 3.4 API設計（概要）

N/A（本プロジェクトはHTTP APIを提供しない。CLIインターフェースはコマンド/オプション仕様として別途定義する）

### 3.5 プロジェクト固有指標（任意）

固有指標-1
指標名: 実行時間（wall-clock）
測定方法: Killer-7の実行ログに開始/終了時刻と経過時間を記録
目標値: 1回のレビュー実行が20分以内
Before/After記録方法: `.ai-review/run.json` に記録（将来の改善比較に利用）

固有指標-2
指標名: LLM呼び出し回数
測定方法: 観点ごとの呼び出し数と合計を記録
目標値: 1回のレビュー実行あたり最大8回（7観点 + 集約1回）
Before/After記録方法: `.ai-review/run.json` に記録

固有指標-3
指標名: evidence整合（P0/P1のverified率）
測定方法: evidence検証統計と最終レポートのP0/P1を照合
目標値: evidence検証が有効な場合、最終結果のP0/P1はすべて `verified=true`
Before/After記録方法: `.ai-review/evidence.json` に統計を記録

---

## 4. Issue分割案

### 4.1 Issue一覧

K7-01
Issue: https://github.com/ToaruPen/Killer-7/issues/1
Issue名: CLI骨格 + Docker実行 + 成果物/終了コード
概要: `killer-7 review` の入口、`.ai-review/` 出力、終了コード規約（0/1/2）を確立する
推定行数: 150-300行
依存: -

K7-02
Issue: https://github.com/ToaruPen/Killer-7/issues/2
Issue名: GitHub PR入力（diff/メタデータ取得して保存）
概要: `--repo/--pr` からPR diff、変更ファイル一覧、HEAD SHA等を取得し成果物として保存する
推定行数: 150-300行
依存: K7-01

K7-03
Issue: https://github.com/ToaruPen/Killer-7/issues/3
Issue名: GitHub content取得ユーティリティ（ref指定/allowlist用）
概要: PRブランチ（ref）からallowlistに一致するファイル内容を取得するユーティリティ（サイズ上限/警告）を追加する
推定行数: 150-300行
依存: K7-02

K7-04
Issue: https://github.com/ToaruPen/Killer-7/issues/4
Issue名: SoT収集（allowlist解決）+ SoT組み立て（切り詰め/警告）
概要: allowlistで指定したSoTをPRブランチから収集し、SoT束（上限250行）を生成して警告を残す
推定行数: 150-300行
依存: K7-03

K7-05
Issue: https://github.com/ToaruPen/Killer-7/issues/5
Issue名: Context Bundle生成（右側/HEAD中心; 上限制御）
概要: diffからContext Bundleを生成し、上限（1500/400/SoT250）を適用して警告を記録する
推定行数: 300行超（例外: config-risk）
依存: K7-02, K7-04

K7-06
Issue: https://github.com/ToaruPen/Killer-7/issues/6
Issue名: opencodeランナー（headless; JSON出力; timeout）
概要: opencodeをヘッドレス実行し、観点別にレビューJSONを生成する（不正出力は終了コード2 + エラー成果物）
推定行数: 150-300行
依存: K7-01

K7-07
Issue: https://github.com/ToaruPen/Killer-7/issues/7
Issue名: 観点プロンプト雛形 + 単一観点ランナー
概要: 7観点プロンプト雛形と、1観点をopencodeで実行してJSONを生成するランナーを実装する
推定行数: 50-150行
依存: K7-05, K7-06

K7-08
Issue: https://github.com/ToaruPen/Killer-7/issues/8
Issue名: 7観点オーケストレータ（並列実行; 最大8呼び出し）
概要: 7観点を並列実行し、観点別JSONを揃える（失敗時の扱いを確定）
推定行数: 150-300行
依存: K7-07

K7-09
Issue: https://github.com/ToaruPen/Killer-7/issues/9
Issue名: schema検証（v3）+ 失敗時エラー成果物
概要: 観点別/集約JSONをschema v3で検証し、失敗時は原因を成果物に残して終了コード2で落とす
推定行数: 50-150行
依存: K7-08

K7-10
Issue: https://github.com/ToaruPen/Killer-7/issues/10
Issue名: evidence検証 + ポリシー適用（格下げ/除外）
概要: `sources`/`code_location` を機械検証し、根拠不明な強い指摘（P0/P1/P2）を格下げ/除外する
推定行数: 150-300行
依存: K7-02, K7-05, K7-09

K7-11
Issue: https://github.com/ToaruPen/Killer-7/issues/11
Issue名: 集約レポート生成（review-summary.json / .md）
概要: 7観点の結果を集約し、レポートと終了コード（Blocked=1）を確定する
推定行数: 150-300行
依存: K7-10

K7-12
Issue: https://github.com/ToaruPen/Killer-7/issues/12
Issue名: PR要約コメント投稿（冪等更新; marker）
概要: `--post` 指定時に要約コメントを冪等更新する
推定行数: 150-300行
依存: K7-11

K7-13
Issue: https://github.com/ToaruPen/Killer-7/issues/13
Issue名: inline用diff行マッピング + 対象選定 + fingerprint仕様
概要: inline投稿に必要なdiff positionマッピングとfingerprint（重複排除）を実装する（投稿処理は別）
推定行数: 50-150行
依存: K7-02, K7-11

K7-14
Issue: https://github.com/ToaruPen/Killer-7/issues/14
Issue名: P0/P1 inline投稿（冪等; 重複排除; 上限150）
概要: `--inline` 指定時にP0/P1のみをinline投稿し、冪等/上限超過時の失敗を実装する
推定行数: 300行超（例外: config-risk）
依存: K7-12, K7-13

K7-15
Issue: https://github.com/ToaruPen/Killer-7/issues/15
Issue名: ハイブリッド運用（repo ro + path allowlist）+ questions再実行導線
概要: デフォルトはdiff+bundle+SoTのみで実行し、必要時のみrepo ro + path allowlistを許可し、questionsで再実行導線を作る
推定行数: 150-300行
依存: K7-11

### 4.2 依存関係図

依存関係（関係を1行ずつ列挙）:
- K7-02 depends_on K7-01
- K7-03 depends_on K7-02
- K7-04 depends_on K7-03
- K7-05 depends_on K7-02
- K7-05 depends_on K7-04
- K7-06 depends_on K7-01
- K7-07 depends_on K7-05
- K7-07 depends_on K7-06
- K7-08 depends_on K7-07
- K7-09 depends_on K7-08
- K7-10 depends_on K7-02
- K7-10 depends_on K7-05
- K7-10 depends_on K7-09
- K7-11 depends_on K7-10
- K7-12 depends_on K7-11
- K7-13 depends_on K7-02
- K7-13 depends_on K7-11
- K7-14 depends_on K7-12
- K7-14 depends_on K7-13
- K7-15 depends_on K7-11

---

## 5. プロダクション品質設計（PRD Q6に応じて記載）

### 5.1 パフォーマンス設計（PRD Q6-7: Yesの場合必須）

PRD Q6-7: Yes

対象操作:
- PRレビュー実行: 20分以内（7観点 + 集約 +（任意）投稿を含む）
- Context Bundle生成: 1500行上限（1ファイル400行、SoT合計250行）を厳守
- inline投稿: P0/P1最大150件（超過時は要約へ退避し、終了コードを失敗にする）

測定方法:
- ツール: Killer-7の実行ログ（開始/終了時刻）、成果物の行数/件数集計
- 環境: Killer-7実行PC（ローカルDocker）
- 条件: PR diffサイズが大きい場合でも上限制御で完走すること

ボトルネック候補:
- LLM API: 観点数が多く待ち時間が支配的
- diff/バンドル: 大規模差分でのI/Oと切り詰め
- GitHub投稿: inline件数が多い場合のAPI呼び出し増

対策方針:
- 観点は並列実行（上限8呼び出しを維持）
- バンドル生成は行数上限で切り詰め、警告をレポートに明記
- inlineはP0/P1のみ + 上限150 + 冪等で更新/削除を行う

### 5.2 セキュリティ設計（PRD Q6-5: Yesの場合必須）

PRD Q6-5: Yes

扱うデータ:
- ソースコード/差分/SoT: 機密（外部送信は最小化したバンドルのみ）
- GitHubトークン（PAT等）: 機密（ログ出力禁止、環境変数のみ）
- LLM APIキー: 機密（ログ出力禁止、環境変数のみ）
- opencodeの認証情報/設定: 機密（ログ出力禁止。Killer-7は取得/生成しない）

認証/認可:
- 認証方式: `gh auth` または `GITHUB_TOKEN`（PAT）
- 認可モデル: 最小権限（対象repoのPR読み取り + コメント/レビューコメント投稿に必要最小）
- セッション管理: 対象外（ローカルCLI）

対策チェックリスト:
- [ ] LLM送信コンテキストはdiff/バンドル/SoTに限定し、repo全文アクセスはデフォルト無効
- [ ] repo全文アクセスを許可する場合もread-only + パスallowlistで制限
- [ ] ログにトークン/APIキー/不要なファイル内容を出力しない（マスキング/抑止）
- [ ] opencodeの認証情報をKiller-7が生成/永続化しない（ユーザーが事前に認証し、必要な設定/シークレットは実行環境で注入する）
- [ ] HTTPSのみを使用（LLM API/ GitHub API）
- [ ] `.ai-review/` の出力は秘密情報を含めない（必要なら権限600/700）

### 5.3 観測性設計（PRD Q6-6: Yesの場合必須）

N/A（監査ログ要件なし。ローカル成果物と実行ログを保存して追跡する）

### 5.4 可用性設計（PRD Q6-8: Yesの場合必須）

N/A（可用性要件なし。ローカルCLIでありSLO/SLAを設定しない）

---

## 6. リスクと対策

リスク-1
リスク: PRブランチ上のSoTが改変され、レビューコンテキストが誘導される
影響度: 中
対策: SoT allowlistを使い、必要ならbaseブランチ参照に切り替え可能な設計にする。SoT差分がある場合は警告を出す

リスク-2
リスク: diffが大きく、バンドルが切り詰められて重要な根拠が落ちる
影響度: 中
対策: 切り詰めは必ず警告としてレポートに残し、questionsで追加抜粋/再実行できる導線を用意する

リスク-3
リスク: opencode経由のLLMが不正JSONを返してパイプラインが停止する
影響度: 中
対策: schema検証で早期に失敗とし、終了コード2 + エラー成果物を保存する

リスク-4
リスク: inline投稿が大量になりPRが荒れる/投稿が失敗する
影響度: 中
対策: P0/P1のみ + 上限150 + 超過時はinline投稿を抑制して要約へ退避し、終了コードはBlocked（1）とする（要約コメントは更新する）

リスク-5
リスク: fork PRでsecrets（LLM APIキー等）を安全に扱えず、レビューが実行できない/事故りやすい
影響度: 中
対策: GitHub Actions運用時はfork PRをデフォルトで実行対象外とし、必要なら別途手動運用（ローカル実行など）に切り替える

---

## 7. マイルストーン

Phase-1
フェーズ: Phase 1（ローカル成果物まで）
完了条件: K7-01〜K7-11が完了し、投稿なしで `review-summary.json/.md` が生成できる

追加（衛生）:

- CI（GitHub Actions）で Python 3.11 の `python -m unittest discover -s tests -p 'test*.py'` が実行され、green である
目標日: なし

Phase-2
フェーズ: Phase 2（PR投稿）
完了条件: K7-12〜K7-14が完了し、要約/inlineが冪等に投稿できる
目標日: なし

Phase-3
フェーズ: Phase 3（ハイブリッド強化）
完了条件: K7-15が完了し、repo ro + allowlistと質問ループが運用できる
目標日: なし

---

## 8. 技術方針別の制限チェック

### シンプル優先の場合

- [ ] 外部サービス数が1以下（例外: PRD必須要件によりGitHub API + LLM APIの2つを使用）
- [ ] 新規導入ライブラリは必要最小限にする（目標: 3以下）。ただし「必須/工数削減+確実性/著名OSS」のいずれかを満たす場合は採用し、理由をIssueに明記する
- [x] 新規コンポーネント数が3以下（単一CLIコンテナのみ）
- [x] 非同期基盤（キュー/イベントストリーム）を使用していない
- [x] マイクロサービス分割をしていない
- [x] コンテナオーケストレーション（K8s等）を使用していない

注記: 外部サービス数はPRD必須要件により例外（GitHub API + LLM API）

### 共通チェック

- [x] 新規技術/サービス名が5つ以下（Docker/Python/opencode/GitHub API/LLM API）
- [x] 各選択に理由がある
- [x] 代替案（よりシンプルな方法）が提示されている
- [x] 「将来のため」だけを理由にした項目がない
- [x] 必須提出物（外部サービス一覧/コンポーネント一覧/新規技術一覧）が揃っている

---

## 9. Unknown項目の確認（PRDから引き継ぎ）

Unknown-1
項目: 期限
PRDの値: Unknown
確認結果: 期限なし

---

## 変更履歴

- 2026-02-05: v1.0 初版作成（@toarupen）
