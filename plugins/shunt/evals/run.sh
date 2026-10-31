#!/bin/bash
# Test runner: hook routing, CLI transport, and optional context-size measurements
#
# Usage:
#   bash evals/run.sh              # hooks + transport (no authentication needed)
#   bash evals/run.sh --benchmark  # also measure live context sizes (requires CLI authentication and SHUNT_BACKEND)
#   bash evals/run.sh --all        # every eval suite

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES="$SCRIPT_DIR/.fixtures"
PASSED=0
FAILED=0
TOTAL=0
RUN_BENCHMARK=false

for arg in "$@"; do
  case "$arg" in
    --benchmark) RUN_BENCHMARK=true ;;
    --all)       RUN_BENCHMARK=true ;;
  esac
done

generate_fixture() {
  local path="$1" lines="$2"
  if [ "$lines" -eq 0 ]; then
    touch "$path"
  else
    seq 1 "$lines" | awk '{print "line "NR}' > "$path"
  fi
}

setup_fixtures() {
  local evals_file="$1"
  rm -rf "$FIXTURES"
  mkdir -p "$FIXTURES"

  local count
  count=$(jq '.evals | length' "$evals_file")

  for ((i = 0; i < count; i++)); do
    local fixture
    fixture=$(jq -r ".evals[$i].fixture" "$evals_file")
    [ "$fixture" = "null" ] && continue

    local lines
    lines=$(jq -r ".evals[$i].fixture.lines" "$evals_file")

    local input_path
    input_path=$(jq -r ".evals[$i].input.tool_input.file_path // empty" "$evals_file")
    if [ -z "$input_path" ]; then
      input_path=$(jq -r ".evals[$i].input.tool_input.command // empty" "$evals_file" | sed -E 's/^(cat|head|tail|less|more) +(-[^ ]+ +)*//' | sed 's/ .*//' | tr -d '"'"'")
    fi
    input_path=$(echo "$input_path" | sed "s|{{FIXTURES}}|$FIXTURES|")

    # Commands the parser is not meant to extract a path from (grep, git, …)
    # reduce to the command name itself. Generating that would drop a junk file
    # in the working directory; the fixtures those evals rely on are created by
    # their siblings anyway.
    case "$input_path" in
      "$FIXTURES"/*) generate_fixture "$input_path" "$lines" ;;
    esac
  done
}

run_eval() {
  local hook="$1" name="$2" input="$3" expected="$4" reason="$5" env_json="$6"
  TOTAL=$((TOTAL + 1))

  local result actual
  if [ -n "$env_json" ] && [ "$env_json" != "null" ]; then
    local env_cmd=""
    while IFS='=' read -r key val; do
      env_cmd="$env_cmd $key=$val"
    done < <(echo "$env_json" | jq -r 'to_entries[] | "\(.key)=\(.value)"')
    result=$(echo "$input" | env $env_cmd bash "$hook" 2>/dev/null)
  else
    result=$(echo "$input" | bash "$hook" 2>/dev/null)
  fi
  actual=$(echo "$result" | jq -r '.decision')

  if [ "$actual" = "$expected" ]; then
    printf "  \033[32mPASS\033[0m  %-30s %s\n" "$name" "$reason"
    PASSED=$((PASSED + 1))
  else
    printf "  \033[31mFAIL\033[0m  %-30s expected=%s got=%s\n" "$name" "$expected" "$actual"
    FAILED=$((FAILED + 1))
  fi
}

run_suite() {
  local hook="$1" evals_file="$2" label="$3"

  setup_fixtures "$evals_file"

  echo ""
  echo "$label"
  echo "────────────────────────────────────────────────────────────────"

  local count
  count=$(jq '.evals | length' "$evals_file")

  for ((i = 0; i < count; i++)); do
    local name expected reason input
    name=$(jq -r ".evals[$i].name" "$evals_file")
    expected=$(jq -r ".evals[$i].expected_decision" "$evals_file")
    reason=$(jq -r ".evals[$i].reason" "$evals_file")
    input=$(jq -c ".evals[$i].input" "$evals_file" | sed "s|{{FIXTURES}}|$FIXTURES|g")

    local env_json
    env_json=$(jq -r ".evals[$i].env // empty" "$evals_file")
    run_eval "$hook" "$name" "$input" "$expected" "$reason" "$env_json"
  done

  rm -rf "$FIXTURES"
}

# ── Transport suite ──

# Runs as a child process: the suite stubs the worker CLIs, and that stub must not
# leak into the benchmarks below, which need the real one.
run_transport_suite() {
  echo ""
  echo "Transport (scripts/lib/worker.py, stubbed Claude/Codex CLIs)"
  echo "────────────────────────────────────────────────────────────────"

  local output counts p f
  output=$(bash "$SCRIPT_DIR/transport-evals.sh" 2>&1) || true

  printf '%s\n' "$output" | grep -v '^## ' || true
  # `|| true` so a missing trailer reaches the fallback below instead of
  # tripping set -e on the failed grep.
  counts=$(printf '%s\n' "$output" | grep '^## ' | tail -1 || true)
  p=$(printf '%s' "$counts" | awk '{print $2}')
  f=$(printf '%s' "$counts" | awk '{print $3}')

  if [ -z "$p" ]; then
    printf "  \033[31mFAIL\033[0m  %-32s suite did not report results\n" "transport-evals"
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
    return
  fi

  PASSED=$((PASSED + p))
  FAILED=$((FAILED + f))
  TOTAL=$((TOTAL + p + f))
}

# Live measurements are optional and must propagate worker errors.
run_benchmarks() {
  python3 "$SCRIPT_DIR/benchmark.py"
}

# ── Main ──

run_suite "$SCRIPT_DIR/../hooks/check-file-size" "$SCRIPT_DIR/hook-evals.json" "Read hook (check-file-size)"
run_suite "$SCRIPT_DIR/../hooks/check-bash-read" "$SCRIPT_DIR/bash-hook-evals.json" "Bash hook (check-bash-read)"
run_transport_suite

echo ""
echo "════════════════════════════════════════════════════════════════"
printf "Total: \033[32m%d passed\033[0m, \033[31m%d failed\033[0m, %d total\n" "$PASSED" "$FAILED" "$TOTAL"

if [ "$RUN_BENCHMARK" = true ]; then
  run_benchmarks
fi

echo ""
[ "$FAILED" -gt 0 ] && exit 1
exit 0
