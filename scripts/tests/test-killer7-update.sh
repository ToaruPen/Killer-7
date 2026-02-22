#!/usr/bin/env bash
set -euo pipefail

eprint() { printf '%s\n' "$*" >&2; }
pass=0
fail=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    eprint "FAIL: $label: expected='$expected' actual='$actual'"
  fi
}

assert_exit() {
  local label="$1" expected="$2"
  shift 2
  local actual=0
  "$@" 2>/dev/null || actual=$?
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    eprint "FAIL: $label: expected exit=$expected actual exit=$actual"
  fi
}

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
update_sh="$repo_root/scripts/killer-7-update.sh"

if [[ ! -f "$update_sh" ]]; then
  eprint "Missing script: $update_sh"
  exit 1
fi

tmpdir="$(mktemp -d 2>/dev/null || mktemp -d -t killer7-update-test)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT



eprint "=== needs_update ==="

assert_exit "needs_update: different versions => update needed" 0 bash -c "source '$update_sh'; needs_update v1.0.0 v1.1.0"

assert_exit "needs_update: same version => no-op" 1 bash -c "source '$update_sh'; needs_update v1.0.0 v1.0.0"

assert_exit "needs_update: empty target => no-op" 1 bash -c "source '$update_sh'; needs_update v1.0.0 ''"

assert_exit "needs_update: empty current, non-empty target => update needed" 0 bash -c "source '$update_sh'; needs_update '' v1.0.0"



eprint "=== load_config ==="

cat > "$tmpdir/config.env" <<'CONF'
KILLER7_CHANNEL=canary
KILLER7_IMAGE=ghcr.io/test/killer-7
KILLER7_HEALTHCHECK_CMD="echo ok"
CONF

result="$(bash -c "source '$update_sh'; load_config '$tmpdir/config.env'; echo \"\$KILLER7_CHANNEL\"")"
assert_eq "load_config: channel from file" "canary" "$result"

result="$(bash -c "source '$update_sh'; load_config '$tmpdir/config.env'; echo \"\$KILLER7_IMAGE\"")"
assert_eq "load_config: image from file" "ghcr.io/test/killer-7" "$result"

result="$(bash -c "source '$update_sh'; load_config ''; echo \"\$KILLER7_CHANNEL\"")"
assert_eq "load_config: default channel" "stable" "$result"

result="$(bash -c "source '$update_sh'; load_config ''; echo \"\$KILLER7_IMAGE\"")"
assert_eq "load_config: default image" "ghcr.io/toarupen/killer-7" "$result"

assert_exit "load_config: missing config file should fail" 1 bash -c "source '$update_sh'; load_config '$tmpdir/not-found.env'"

cat > "$tmpdir/config-malformed.env" <<'CONF'
THIS_IS_NOT_VALID
CONF

assert_exit "load_config: malformed line should fail" 1 bash -c "source '$update_sh'; load_config '$tmpdir/config-malformed.env'"

safe_marker="$tmpdir/unsafe-marker"
cat > "$tmpdir/config-safe.env" <<CONF
KILLER7_IMAGE=\$(touch "$safe_marker")
UNKNOWN_KEY=ignored
CONF

expected_literal="\$(touch \"$safe_marker\")"
result="$(bash -c "source '$update_sh'; load_config '$tmpdir/config-safe.env'; echo \"\$KILLER7_IMAGE\"")"
assert_eq "load_config: command substitution remains literal" "$expected_literal" "$result"

if [[ -e "$safe_marker" ]]; then
  fail=$((fail + 1))
  eprint "FAIL: load_config should not execute command substitutions"
else
  pass=$((pass + 1))
fi

eprint "=== resolve_target_tag: stable/canary should exclude draft ==="

result="$(bash -c '
  source "'"$update_sh"'"
  gh() {
    local args="$*"
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".prerelease | not"* && "$args" == *".draft | not"* && "$args" == *".tag_name | test"* ]]; then
      echo "v1.2.3"
      return 0
    fi
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".draft | not"* && "$args" == *"-[0-9A-Za-z.-]+$"* && "$args" == *".tag_name | test"* ]]; then
      echo "v1.3.0-canary.1"
      return 0
    fi
    return 1
  }
  resolve_target_tag stable ghcr.io/toarupen/killer-7
')"
assert_eq "resolve_target_tag: stable returns non-draft stable tag" "v1.2.3" "$result"

result="$(bash -c '
  source "'"$update_sh"'"
  gh() {
    local args="$*"
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".prerelease | not"* && "$args" == *".draft | not"* && "$args" == *".tag_name | test"* ]]; then
      echo "v1.2.3"
      return 0
    fi
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".draft | not"* && "$args" == *"-[0-9A-Za-z.-]+$"* && "$args" == *".tag_name | test"* ]]; then
      echo "v1.3.0-canary.1"
      return 0
    fi
    return 1
  }
  resolve_target_tag canary ghcr.io/toarupen/killer-7
')"
assert_eq "resolve_target_tag: canary returns non-draft prerelease tag" "v1.3.0-canary.1" "$result"

result="$(bash -c '
  source "'"$update_sh"'"
  gh() {
    local args="$*"
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".draft | not"* && "$args" == *"-[0-9A-Za-z.-]+$"* && "$args" == *".tag_name | test"* ]]; then
      echo ""
      return 0
    fi
    if [[ "$args" == *"api --paginate repos/toarupen/killer-7/releases?per_page=100"* && "$args" == *".prerelease | not"* && "$args" == *".draft | not"* && "$args" == *".tag_name | test"* ]]; then
      echo "v1.2.3"
      return 0
    fi
    return 1
  }
  resolve_target_tag canary ghcr.io/toarupen/killer-7
')"
assert_eq "resolve_target_tag: canary falls back to stable non-draft tag" "v1.2.3" "$result"

eprint "=== get_current_version: fallback should ignore current/latest ==="

result="$(bash -c "
  source '$update_sh'
  docker() {
    if [[ \"\$1\" == \"inspect\" && \"\$2\" == \"--format\" ]]; then
      local fmt=\"\$3\"
      if [[ \"\$fmt\" == *'index .Config.Labels'* ]]; then
        return 1
      fi
      printf '%s\\n' 'ghcr.io/toarupen/killer-7:current'
      printf '%s\\n' 'ghcr.io/toarupen/killer-7:v1.2.3'
      printf '%s\\n' 'ghcr.io/toarupen/killer-7:latest'
      return 0
    fi
    return 1
  }
  get_current_version ghcr.io/toarupen/killer-7
")"
assert_eq "get_current_version: fallback picks semantic tag" "v1.2.3" "$result"



eprint "=== main: no-op when same version ==="

cat > "$tmpdir/stub-noop.sh" <<'STUB'
resolve_target_tag() { echo "v1.0.0"; }
get_current_version() { echo "v1.0.0"; }
STUB

result="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-noop.sh'
  main 2>/dev/null
  echo \$?
")"
assert_eq "main: no-op exit code" "0" "$result"

stderr_out="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-noop.sh'
  main
" 2>&1 >/dev/null || true)"
if [[ "$stderr_out" == *"no-op"* ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  eprint "FAIL: main: no-op should log 'no-op'"
fi

eprint "=== main: update when new version available ==="

cat > "$tmpdir/stub-update.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 0; }
run_healthcheck() { return 0; }
ACTIVATE_CALLED=""
activate_image() { ACTIVATE_CALLED="yes:$1:$2"; }
STUB

result="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-update.sh'
  main 2>/dev/null
  echo \$?
")"
assert_eq "main: update success exit code" "0" "$result"

stderr_out="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-update.sh'
  main
" 2>&1 >/dev/null || true)"
if [[ "$stderr_out" == *"update complete"* ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  eprint "FAIL: main: update should log 'update complete'"
fi

result="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-update.sh'
  main >/dev/null 2>&1 || true
  echo \"\$ACTIVATE_CALLED\"
")"
assert_eq "main: update should activate target image after healthcheck" "yes:ghcr.io/toarupen/killer-7:v1.1.0" "$result"

eprint "=== main: healthcheck failure => rollback + exit 1 ==="

cat > "$tmpdir/stub-hc-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 0; }
run_healthcheck() { return 1; }
ROLLBACK_CALLED=""
rollback() { ROLLBACK_CALLED="yes:$1:$2"; }
STUB

assert_exit "main: healthcheck fail => exit 1" 1 bash -c "source '$update_sh'; source '$tmpdir/stub-hc-fail.sh'; main"

result="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-hc-fail.sh'
  main >/dev/null 2>&1 || true
  echo \"\$ROLLBACK_CALLED\"
")"
assert_eq "main: rollback should use previous image ref" "yes:ghcr.io/toarupen/killer-7:sha256:prev" "$result"

stderr_out="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-hc-fail.sh'
  main
" 2>&1 >/dev/null || true)"
if [[ "$stderr_out" == *"rolling back"* ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  eprint "FAIL: main: healthcheck failure should log 'rolling back'"
fi

eprint "=== run_healthcheck: command execution via sh -lc ==="

hc_args="$(bash -c "
  source '$update_sh'
  docker() {
    local i=1
    for arg in \"\$@\"; do
      printf '%s|%s\\n' \"\$i\" \"\$arg\"
      i=\$((i + 1))
    done
  }
  run_healthcheck ghcr.io/test/killer-7 v1.2.3 'killer-7 review --help'
")"

if [[ "$hc_args" == *"3|--entrypoint"* && "$hc_args" == *"4|sh"* && "$hc_args" == *"6|-lc"* && "$hc_args" == *"7|killer-7 review --help"* ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  eprint "FAIL: run_healthcheck should execute via sh -lc with full command string"
fi

eprint "=== main: canary channel from config ==="

cat > "$tmpdir/canary-config.env" <<'CONF'
KILLER7_CHANNEL=canary
CONF

cat > "$tmpdir/stub-canary.sh" <<'STUB'
resolve_target_tag() {
  local channel="$1"
  if [[ "$channel" == "canary" ]]; then
    echo "v1.2.0-canary.1"
  else
    echo "v1.1.0"
  fi
}
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 0; }
run_healthcheck() { return 0; }
activate_image() { return 0; }
STUB

result="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-canary.sh'
  main --config '$tmpdir/canary-config.env' 2>/dev/null
  echo \$?
")"
assert_eq "main: canary update success" "0" "$result"

stderr_out="$(bash -c "
  source '$update_sh'
  source '$tmpdir/stub-canary.sh'
  main --config '$tmpdir/canary-config.env'
" 2>&1 >/dev/null || true)"
if [[ "$stderr_out" == *"v1.2.0-canary.1"* ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  eprint "FAIL: main: canary should use canary tag in log"
fi

eprint "=== main: resolve failure => exit 2 ==="

cat > "$tmpdir/stub-resolve-fail.sh" <<'STUB'
resolve_target_tag() { echo ""; }
get_current_version() { echo "v1.0.0"; }
STUB

assert_exit "main: resolve failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-resolve-fail.sh'; main"

eprint "=== main: invalid image format => exit 2 ==="

cat > "$tmpdir/bad-image-tag.env" <<'CONF'
KILLER7_IMAGE=ghcr.io/toarupen/killer-7:latest
CONF

assert_exit "main: image with tag should fail" 2 bash -c "source '$update_sh'; main --config '$tmpdir/bad-image-tag.env'"

cat > "$tmpdir/bad-image-registry.env" <<'CONF'
KILLER7_IMAGE=docker.io/library/killer-7
CONF

assert_exit "main: non-ghcr image should fail" 2 bash -c "source '$update_sh'; main --config '$tmpdir/bad-image-registry.env'"

eprint "=== main: unknown channel => exit 2 ==="

cat > "$tmpdir/bad-channel.env" <<'CONF'
KILLER7_CHANNEL=unknown
CONF

assert_exit "main: unknown channel => exit 2" 2 bash -c "source '$update_sh'; main --config '$tmpdir/bad-channel.env'"

eprint "=== main: pull failure => exit 2 ==="

cat > "$tmpdir/stub-pull-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 1; }
STUB

assert_exit "main: pull failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-pull-fail.sh'; main"

eprint "=== main: rollback failure => exit 2 ==="

cat > "$tmpdir/stub-rollback-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 0; }
run_healthcheck() { return 1; }
rollback() { return 1; }
STUB

assert_exit "main: rollback failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-rollback-fail.sh'; main"

eprint "=== main: activate failure => exit 2 ==="

cat > "$tmpdir/stub-activate-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
get_current_image_ref() { echo "sha256:prev"; }
pull_image() { return 0; }
run_healthcheck() { return 0; }
activate_image() { return 1; }
STUB

assert_exit "main: activate failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-activate-fail.sh'; main"



eprint ""
eprint "Results: pass=$pass fail=$fail"
if [[ "$fail" -gt 0 ]]; then
  eprint "FAILED"
  exit 1
fi
eprint "ALL PASSED"
exit 0
