# Killer-7 Auto-Update Runbook

## Overview

This runbook describes how to automatically update a deployed Killer-7 Docker image on a managed machine, using release tags as the source of truth.

Two channels are supported:
- `stable`
- `canary`

If the post-update health check fails, the updater rolls back to the previous version automatically.

## Prerequisites

- Docker is installed
- `gh` (GitHub CLI) is installed and authenticated
- The host can access `ghcr.io` (`docker pull ghcr.io/toarupen/killer-7:*`)

## Setup

### 1. Pull the initial image

```bash
docker pull ghcr.io/toarupen/killer-7:latest
docker tag ghcr.io/toarupen/killer-7:latest ghcr.io/toarupen/killer-7:current
```

### 2. Create an optional config file

`/etc/killer-7/update.env`:

```bash
KILLER7_CHANNEL=stable
KILLER7_IMAGE=ghcr.io/toarupen/killer-7
KILLER7_HEALTHCHECK_CMD="killer-7 review --help"
```

Channel behavior:
- `stable`: latest non-prerelease release tag
- `canary`: latest prerelease tag, with fallback to `stable` if none exists

### 3. Install the update script

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

Keep `KILLER7_UPDATE_SCRIPT_REF` and `KILLER7_UPDATE_SCRIPT_SHA256` pinned to approved values.

### 4. Configure cron (example: daily at 03:00)

```cron
0 3 * * * /usr/local/bin/killer-7-update --config /etc/killer-7/update.env >> /var/log/killer-7-update.log 2>&1
```

## Update Flow

1. Read the config file for channel, image name, and health check command.
2. Query the GitHub Releases API for the newest tag in the selected channel.
3. Compare it with the current `:current` image tag. If unchanged, exit as no-op.
4. Pull the new image without switching `:current` yet.
5. Run the health check with `docker run --rm --entrypoint sh <image>:<tag> -lc "<cmd>"`.
6. If the health check passes, retag the image as `:current` and exit successfully.
7. If the health check fails, roll back to the previous version and exit with a failure code.

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success (updated or no-op) |
| `1` | Health check failed and rollback succeeded |
| `2` | Fatal error (config, network, Docker, or rollback failure) |

## Manual Rollback

If automatic rollback does not recover the system, restore the previous version manually:

```bash
docker tag ghcr.io/toarupen/killer-7:<previous-version-tag> ghcr.io/toarupen/killer-7:current
docker run --rm ghcr.io/toarupen/killer-7:current review --help
```

## Incident Recovery

1. Inspect `/var/log/killer-7-update.log`.
2. If exit code is `1`, the health check failed but rollback already completed. Investigate the cause, then retry manually.
3. If exit code is `2`, check configuration, network, Docker, `gh auth status`, and `docker info`.
4. If cron did not run, inspect `crontab -l` and system logs.

## Operating the Canary Channel

Canary lets you deploy prerelease versions before they reach `stable`.

```bash
KILLER7_CHANNEL=canary
```

If no prerelease exists, canary falls back to the newest stable tag.
If problems appear, switch back to:

```bash
KILLER7_CHANNEL=stable
```
