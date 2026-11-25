#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s EXPERIMENT.toml CASE_NAME [EXPANDED_OUTPUT.toml]\n' "$0" >&2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 2
fi

if ! command -v tactus >/dev/null 2>&1; then
  printf 'Error: tactus was not found on PATH\n' >&2
  exit 127
fi

run_dir=$(pwd -P)
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

experiment_config=$(realpath -- "$1")
case_name=$2
if [[ -z $case_name ]]; then
  printf 'Error: CASE_NAME must not be empty\n' >&2
  exit 2
fi
if [[ ! -f $experiment_config ]]; then
  printf 'Error: experiment config not found: %s\n' "$experiment_config" >&2
  exit 1
fi

if [[ $# -eq 3 ]]; then
  expanded_config=$(realpath -m -- "$3")
else
  experiment_name=$(basename -- "$experiment_config")
  experiment_stem=${experiment_name%.toml}
  expanded_config="$run_dir/${experiment_stem}_expanded_from_config.toml"
fi

expand_config="$script_dir/expand_for_verif.toml"
plugin_config="$script_dir/tactusharpverif_plugin.toml"
configure_file="$run_dir/configure_verif"
if [[ ! -f $expand_config || ! -f $plugin_config ]]; then
  printf 'Error: expected expansion and plugin TOML files beside this script\n' >&2
  exit 1
fi
if [[ -L $configure_file || ( -e $configure_file && ! -f $configure_file ) ]]; then
  printf 'Error: %s exists and is not a regular file\n' "$configure_file" >&2
  exit 1
fi

had_configure_file=false
backup_file=
if [[ -f $configure_file ]]; then
  had_configure_file=true
  backup_file=$(mktemp "$run_dir/.configure_verif.backup.XXXXXX")
  cp -p -- "$configure_file" "$backup_file"
fi

cleanup() {
  if [[ $had_configure_file == true ]]; then
    cp -p -- "$backup_file" "$configure_file"
    rm -f -- "$backup_file"
  else
    rm -f -- "$configure_file"
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n%s\n%s\n' \
  '--config-file' "$expanded_config" "$plugin_config" > "$configure_file"

tactus case --config-file "$experiment_config" "$expand_config" \
  --expand-config --o "$expanded_config"

tactus case '?configure_verif' --case-name "$case_name" --start-suite
