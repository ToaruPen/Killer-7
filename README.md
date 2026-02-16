# Killer-7

Killer-7は、GitHub PRを入力として、複数観点のLLMレビューを自動実行し、レポート生成とPRコメント投稿（要約/inline）まで行うためのローカルCLI（Docker実行）です。

## 目的

- 開発で利用するLLMのquota消費を抑えつつ、LLM由来のコード劣化/破綻を防ぐ
- diff + Context Bundle + SoT（Source of Truth）allowlistを軸に、schema/evidenceの機械検証で“根拠のない強い指摘”を抑制する

## 仕様（SoT）

- PRD: `docs/prd/killer-7.md`
- Epic: `docs/epics/killer-7-epic.md`

## テスト

Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-killer7.txt

python3.11 -m unittest discover -s tests -p 'test*.py'
```

## 成果物

- 出力先: `./.ai-review/`
- 最低限の実行メタ: `./.ai-review/run.json`
- PR入力（K7-02）:
  - `./.ai-review/diff.patch`
  - `./.ai-review/changed-files.tsv`
  - `./.ai-review/meta.json`

- evidence検証（K7-10）:
  - `./.ai-review/evidence.json`
  - `./.ai-review/aspects/<aspect>.raw.json`
  - `./.ai-review/aspects/<aspect>.evidence.json`
  - `./.ai-review/aspects/<aspect>.policy.json`
  - `./.ai-review/aspects/index.evidence.json`
  - `./.ai-review/aspects/index.policy.json`

## 終了コード

- 0: 成功
- 1: Blocked（前提条件不足。ユーザー対応が必要）
- 2: 実行失敗（入力不正/実行時エラー）

## Docker（開発中の最小動作）

```bash
docker build -t killer-7 .

# カレントに成果物を出す（所有権を合わせたい場合は -u を付ける）
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD":/work -w /work killer-7 \
  review --repo owner/name --pr 123
```

## 想定する使い方（v1）

Killer-7は開発PCとは別PCでも運用でき、GitHub上のPRを入力にレビューを実行します。

```bash
# PR番号を入力にしてレビュー（投稿なし）
killer-7 review --repo owner/name --pr 123

# 普段の運用（コスト/時間を抑える）: 観点を絞って実行
killer-7 review --repo owner/name --pr 123 --aspect correctness
killer-7 review --repo owner/name --pr 123 --aspect correctness --aspect security

# 重要PR（フルレビュー）: 7観点（デフォルト; 明示するなら --preset full）
killer-7 review --repo owner/name --pr 123 --preset full

# 要約コメント投稿
killer-7 review --repo owner/name --pr 123 --post

# 要約 + inline（P0/P1）投稿
killer-7 review --repo owner/name --pr 123 --post --inline

# 探索モード（作業ツリー探索を許可し、証跡を保存）
killer-7 review --repo owner/name --pr 123 --explore
```

注記:

- 実体はDockerで実行し、成果物は `./.ai-review/` 配下に保存する想定です
- デフォルトはdiff + Context Bundle + SoTのみをLLMへ渡し、必要時のみrepo read-only + path allowlistで追加コンテキストを許可します（ハイブリッド）
- オプション一覧は `killer-7 review --help` を参照してください

探索モード（`--explore`）:

- OpenCode が repo を探索（read + bash/git）して不足文脈を補えるようにします
- 探索の証跡を `.ai-review/` に保存し、後段の evidence 検証で「探索由来の根拠」も verified 扱いにできます
- bash は読み取り専用の git コマンドに限定され、許可外のコマンドやフラグ不足は Blocked（終了コード 1）になります
- read は git 管理ファイルに限定し、`.git/` や `.ai-review/` などの機微領域は読み取り禁止です
- ポリシーは tool trace（OpenCodeのJSONLイベント）を事後検証して適用します（違反は Blocked）。OpenCode 側の実行経路を完全にサンドボックス化するものではない点に注意してください
- 上限は環境変数で調整できます（例: `KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES`, `KILLER7_EXPLORE_MAX_TOOL_CALLS`, `KILLER7_EXPLORE_MAX_BASH_CALLS`, `KILLER7_EXPLORE_MAX_READ_LINES`, `KILLER7_EXPLORE_MAX_FILES`, `KILLER7_EXPLORE_MAX_BUNDLE_BYTES`）

主な成果物（追加）:

- `./.ai-review/tool-trace.jsonl`
- `./.ai-review/tool-bundle.txt`（read対象のパス+行番号+該当行の抜粋。秘密情報はredact）
- `./.ai-review/opencode/<aspect-*>/stdout.jsonl`（JSONLイベントをredactして保存。tool_useのoutput等は除去）

## プロジェクト固有設定の生成

Epicからプロジェクト固有のスキル/ルールを生成できます（生成物はgit管理しません）。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-agentic-sdd.txt

python3 scripts/generate-project-config.py docs/epics/killer-7-epic.md
```

生成先: `.agentic-sdd/project/`
