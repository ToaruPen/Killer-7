#!/usr/bin/env bash
# killer-7-update.sh - Auto-update Killer-7 Docker image from ghcr.io
#
# Usage:
#   scripts/killer-7-update.sh [--config <path>]
#
# Configuration (via config file or env):
#   KILLER7_CHANNEL         stable|canary  (default: stable)
#   KILLER7_IMAGE           Docker image base (default: ghcr.io/toarupen/killer-7)
#   KILLER7_HEALTHCHECK_CMD Command to verify after update (default: killer-7 review --help)
#
# Exit codes:
#   0 - Success (updated or no-op)
#   1 - Healthcheck failed, rolled back
#   2 - Fatal error (config/network/docker)

set -euo pipefail

readonly KILLER7_DEFAULT_IMAGE="ghcr.io/toarupen/killer-7"
readonly KILLER7_DEFAULT_CHANNEL="stable"
readonly KILLER7_DEFAULT_HEALTHCHECK_CMD="killer-7 review --help"

log_info()  { printf '[INFO]  %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
log_error() { printf '[ERROR] %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }


load_config() {
  local config_file="${1:-}"
  local line key value
  if [[ -n "$config_file" ]]; then
    if [[ ! -f "$config_file" ]]; then
      log_error "Config file not found: $config_file"
      return 1
    fi
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%$'\r'}"
      [[ "$line" =~ ^[[:space:]]*$ ]] && continue
      [[ "$line" =~ ^[[:space:]]*# ]] && continue
      if [[ ! "$line" =~ ^[[:space:]]*([A-Z0-9_]+)[[:space:]]*=(.*)$ ]]; then
        log_error "Malformed config line: $line"
        return 1
      fi

      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      if [[ "$value" =~ ^\"(.*)\"$ ]]; then
        value="${BASH_REMATCH[1]}"
      elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
        value="${BASH_REMATCH[1]}"
      fi

      case "$key" in
        KILLER7_IMAGE)
          KILLER7_IMAGE="$value"
          ;;
        KILLER7_CHANNEL)
          KILLER7_CHANNEL="$value"
          ;;
        KILLER7_HEALTHCHECK_CMD)
          KILLER7_HEALTHCHECK_CMD="$value"
          ;;
      esac
    done < "$config_file"
  fi
  KILLER7_IMAGE="${KILLER7_IMAGE:-$KILLER7_DEFAULT_IMAGE}"
  KILLER7_CHANNEL="${KILLER7_CHANNEL:-$KILLER7_DEFAULT_CHANNEL}"
  KILLER7_HEALTHCHECK_CMD="${KILLER7_HEALTHCHECK_CMD:-$KILLER7_DEFAULT_HEALTHCHECK_CMD}"
}


resolve_release_tag() {
  local repo_owner_name="$1"
  local jq_filter="$2"
  local gh_output
  if ! gh_output="$(gh api --paginate "repos/${repo_owner_name}/releases?per_page=100" --jq "$jq_filter" 2>&1)"; then
    log_error "Failed gh release query for ${repo_owner_name}: ${gh_output}"
    return 1
  fi
  printf '%s\n' "$gh_output" | head -n1
}

resolve_target_tag() {
  local channel="$1"
  local image="$2"
  local repo_owner_name
  repo_owner_name="${image#ghcr.io/}"

  local tag=""
  case "$channel" in
    stable)
      if ! tag="$(resolve_release_tag "$repo_owner_name" '.[] | select((.prerelease | not) and (.draft | not) and (.tag_name | test("^v?[0-9]+\\.[0-9]+\\.[0-9]+$"))) | .tag_name')"; then
        return 1
      fi
      ;;
    canary)
      if ! tag="$(resolve_release_tag "$repo_owner_name" '.[] | select((.draft | not) and (.tag_name | test("^v?[0-9]+\\.[0-9]+\\.[0-9]+-[0-9A-Za-z.-]+$"))) | .tag_name')"; then
        return 1
      fi
      if [[ -z "$tag" ]]; then
        if ! tag="$(resolve_release_tag "$repo_owner_name" '.[] | select((.prerelease | not) and (.draft | not) and (.tag_name | test("^v?[0-9]+\\.[0-9]+\\.[0-9]+$"))) | .tag_name')"; then
          return 1
        fi
      fi
      ;;
    *)
      log_error "Unknown channel: $channel"
      echo ""
      return 1
      ;;
  esac
  echo "$tag"
}

get_current_version() {
  local image="$1"
  local current_tag=""
  current_tag="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "${image}:current" 2>/dev/null || echo "")"
  if [[ -z "$current_tag" || "$current_tag" == "<no value>" ]]; then
    current_tag="$(
      docker inspect --format '{{range .RepoTags}}{{println .}}{{end}}' "${image}:current" 2>/dev/null \
        | sed "s|^${image}:||" \
        | grep -Ev '^(current|latest)$' \
        | head -1 \
        || echo ""
    )"
  fi
  echo "$current_tag"
}

get_current_image_ref() {
  local image="$1"
  docker image inspect --format '{{.Id}}' "${image}:current" 2>/dev/null || echo ""
}


# Returns 0 if update is needed, 1 if no-op.
needs_update() {
  local current="$1"
  local target="$2"
  if [[ -z "$target" ]]; then
    return 1
  fi
  if [[ "$current" == "$target" ]]; then
    return 1
  fi
  return 0
}

pull_image() {
  local image="$1"
  local tag="$2"
  log_info "pulling ${image}:${tag}"
  docker pull "${image}:${tag}"
}

activate_image() {
  local image="$1"
  local tag="$2"
  docker tag "${image}:${tag}" "${image}:current"
}

run_healthcheck() {
  local image="$1"
  local tag="$2"
  local cmd="$3"
  log_info "healthcheck: ${image}:${tag} cmd='$cmd'"
  if ! docker run --rm --entrypoint sh "${image}:${tag}" -lc "$cmd"; then
    return 1
  fi
  return 0
}

rollback() {
  local image="$1"
  local previous_ref="$2"
  if [[ -z "$previous_ref" ]]; then
    log_error "rollback failed: previous image reference is empty"
    return 1
  fi

  log_info "rollback: restoring ${previous_ref} as ${image}:current"
  if ! docker image inspect "$previous_ref" >/dev/null 2>&1; then
    log_error "rollback failed: image not found ${previous_ref}"
    return 1
  fi

  if ! docker tag "$previous_ref" "${image}:current"; then
    log_error "rollback failed: docker tag ${previous_ref} -> ${image}:current"
    return 1
  fi

  return 0
}


main() {
  local config_file=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        config_file="${2:-}"
        if [[ -z "$config_file" ]]; then
          log_error "--config requires a path argument"
          return 2
        fi
        shift 2
        ;;
      *)
        log_error "Unknown argument: $1"
        return 2
        ;;
    esac
  done

  if ! load_config "$config_file"; then
    return 2
  fi

  if [[ "$KILLER7_IMAGE" == *@* || "$KILLER7_IMAGE" =~ :[^/]+$ ]]; then
    log_error "KILLER7_IMAGE must be a base image without tag/digest: $KILLER7_IMAGE"
    return 2
  fi
  if [[ "$KILLER7_IMAGE" != ghcr.io/*/* ]]; then
    log_error "KILLER7_IMAGE must be ghcr.io/<owner>/<repo>: $KILLER7_IMAGE"
    return 2
  fi
  if [[ -z "$KILLER7_HEALTHCHECK_CMD" ]]; then
    log_error "KILLER7_HEALTHCHECK_CMD must not be empty: '$KILLER7_HEALTHCHECK_CMD'"
    return 2
  fi

  log_info "channel=$KILLER7_CHANNEL image=$KILLER7_IMAGE"

  local target_tag
  if ! target_tag="$(resolve_target_tag "$KILLER7_CHANNEL" "$KILLER7_IMAGE")"; then
    log_error "Failed to resolve target tag for channel=$KILLER7_CHANNEL"
    return 2
  fi
  if [[ -z "$target_tag" ]]; then
    log_error "Failed to resolve target tag for channel=$KILLER7_CHANNEL"
    return 2
  fi

  local current_version
  current_version="$(get_current_version "$KILLER7_IMAGE")"

  if ! needs_update "$current_version" "$target_tag"; then
    log_info "no-op: current=$current_version target=$target_tag"
    return 0
  fi

  log_info "updating: current=$current_version target=$target_tag"

  local previous_image_ref
  previous_image_ref="$(get_current_image_ref "$KILLER7_IMAGE")"

  if ! pull_image "$KILLER7_IMAGE" "$target_tag"; then
    log_error "Failed to pull image: $KILLER7_IMAGE:$target_tag"
    return 2
  fi

  if ! run_healthcheck "$KILLER7_IMAGE" "$target_tag" "$KILLER7_HEALTHCHECK_CMD"; then
    log_error "Healthcheck failed for $KILLER7_IMAGE:$target_tag, rolling back to $current_version"
    if ! rollback "$KILLER7_IMAGE" "$previous_image_ref"; then
      log_error "Rollback failed after healthcheck failure"
      return 2
    fi
    return 1
  fi

  if ! activate_image "$KILLER7_IMAGE" "$target_tag"; then
    log_error "Failed to activate image: $KILLER7_IMAGE:$target_tag"
    return 2
  fi

  log_info "update complete: $KILLER7_IMAGE:$target_tag"
  return 0
}

# Allow sourcing for testing without executing main.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
