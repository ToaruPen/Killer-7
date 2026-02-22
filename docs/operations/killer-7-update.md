# Killer-7 自動更新 運用手順

## 概要

管理PCへ配布した Killer-7 Docker image を、リリースタグ基準で自動更新する。
stable/canary の2チャネルを運用し、ヘルスチェック失敗時は直前バージョンへ自動ロールバックする。

## 前提条件

- Docker がインストール済み
- `gh` (GitHub CLI) がインストール・認証済み
- ghcr.io へのアクセスが可能（`docker pull ghcr.io/toarupen/killer-7:*`）

## 導入

### 1. 初回イメージ取得

```bash
docker pull ghcr.io/toarupen/killer-7:latest
docker tag ghcr.io/toarupen/killer-7:latest ghcr.io/toarupen/killer-7:current
```

### 2. 設定ファイル作成（任意）

`/etc/killer-7/update.env`:

```bash
KILLER7_CHANNEL=stable
KILLER7_IMAGE=ghcr.io/toarupen/killer-7
KILLER7_HEALTHCHECK_CMD="killer-7 review --help"
```

チャネル:
- `stable`: 最新の正式リリースタグ
- `canary`: 最新のプレリリースタグ（なければ stable にフォールバック）

### 3. 更新スクリプト配置

```bash
KILLER7_UPDATE_SCRIPT_REF="v0.2.0"
KILLER7_UPDATE_SCRIPT_SHA256="<approved-sha256>"
tmp_script="$(mktemp)"
curl -fsSL "https://raw.githubusercontent.com/ToaruPen/Killer-7/${KILLER7_UPDATE_SCRIPT_REF}/scripts/killer-7-update.sh" \
  -o "$tmp_script"
echo "${KILLER7_UPDATE_SCRIPT_SHA256}  ${tmp_script}" | sha256sum -c -
install -m 0755 "$tmp_script" /usr/local/bin/killer-7-update
rm -f "$tmp_script"
```

`KILLER7_UPDATE_SCRIPT_REF` と `KILLER7_UPDATE_SCRIPT_SHA256` は、運用で承認済みの値に固定して管理する。

### 4. cron 設定（例: 毎日 3:00）

```cron
0 3 * * * /usr/local/bin/killer-7-update --config /etc/killer-7/update.env >> /var/log/killer-7-update.log 2>&1
```

## 更新フロー

1. 設定ファイルを読み込み（チャネル・イメージ名・ヘルスチェックコマンド）
2. GitHub Releases API から対象チャネルの最新タグを取得
3. 現在の `:current` タグと比較し、同一なら no-op で終了（exit 0）
4. 新バージョンを `docker pull`（まだ `:current` へ切替しない）
5. ヘルスチェック実行（`docker run --rm --entrypoint sh <image>:<tag> -lc "<cmd>"`）
6. 成功: `:current` へ切替して正常終了（exit 0）
7. 失敗: 直前バージョンへロールバックし、エラーログを出力して exit 1

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 成功（更新完了 or no-op） |
| 1 | ヘルスチェック失敗、ロールバック済み |
| 2 | 致命的エラー（設定不備/ネットワーク/Docker/ロールバック失敗） |

## 手動ロールバック

自動ロールバックが動作しない場合の復旧手順:

```bash
docker tag ghcr.io/toarupen/killer-7:<前バージョンタグ> ghcr.io/toarupen/killer-7:current
docker run --rm ghcr.io/toarupen/killer-7:current review --help
```

## 障害時の復旧

1. `/var/log/killer-7-update.log` を確認
2. 終了コードが 1: ヘルスチェック失敗。ロールバック済みのため、原因調査後に手動で再更新
3. 終了コードが 2: 設定/ネットワーク/Docker の問題。`gh auth status` と `docker info` を確認
4. cron が実行されていない: `crontab -l` と syslog を確認

## canary チャネルの運用

canary を使うと、正式リリース前のバージョンを先行適用できる。

```bash
KILLER7_CHANNEL=canary
```

canary にプレリリースがない場合は、stable の最新タグにフォールバックする。
問題が発生した場合は `KILLER7_CHANNEL=stable` に戻すことで安全なバージョンに復帰できる。
