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

(
  # shellcheck disable=SC1090
  source "$update_sh"
  if needs_update "v1.0.0" "v1.1.0"; then
    exit 0
  else
    exit 1
  fi
)
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
pull_image() { return 0; }
run_healthcheck() { return 0; }
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

eprint "=== main: healthcheck failure => rollback + exit 1 ==="

cat > "$tmpdir/stub-hc-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
pull_image() { return 0; }
run_healthcheck() { return 1; }
ROLLBACK_CALLED=""
rollback() { ROLLBACK_CALLED="yes:$1:$2"; }
STUB

assert_exit "main: healthcheck fail => exit 1" 1 bash -c "source '$update_sh'; source '$tmpdir/stub-hc-fail.sh'; main"

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

if [[ "$hc_args" == *"4|sh"* && "$hc_args" == *"5|-lc"* && "$hc_args" == *"6|killer-7 review --help"* ]]; then
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
pull_image() { return 0; }
run_healthcheck() { return 0; }
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

eprint "=== main: pull failure => exit 2 ==="

cat > "$tmpdir/stub-pull-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
pull_image() { return 1; }
STUB

assert_exit "main: pull failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-pull-fail.sh'; main"

eprint "=== main: rollback failure => exit 2 ==="

cat > "$tmpdir/stub-rollback-fail.sh" <<'STUB'
resolve_target_tag() { echo "v1.1.0"; }
get_current_version() { echo "v1.0.0"; }
pull_image() { return 0; }
run_healthcheck() { return 1; }
rollback() { return 1; }
STUB

assert_exit "main: rollback failure => exit 2" 2 bash -c "source '$update_sh'; source '$tmpdir/stub-rollback-fail.sh'; main"



eprint ""
eprint "Results: pass=$pass fail=$fail"
if [[ "$fail" -gt 0 ]]; then
  eprint "FAILED"
  exit 1
fi
eprint "ALL PASSED"
exit 0
