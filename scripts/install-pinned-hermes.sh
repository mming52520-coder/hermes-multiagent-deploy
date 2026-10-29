#!/usr/bin/env bash
set -Eeuo pipefail
# Run only during an explicitly requested installation, never from tests.
scratch_dir="$(mktemp -d)"
trap 'rm -f -- "$scratch_dir/install.sh"; rmdir -- "$scratch_dir"' EXIT
commit=aaf5691261f12601db845386d650dce1cdfa30f9
curl --fail --show-error --location \
  "https://raw.githubusercontent.com/NousResearch/hermes-agent/$commit/scripts/install.sh" \
  --output "$scratch_dir/install.sh"
printf '%s  %s\n' c2e4326c1660bd45f64321996eb15bda35e7a4649e32a310495a61972a2804c8 \
  "$scratch_dir/install.sh" | sha256sum --check --status
bash "$scratch_dir/install.sh" --commit "$commit" --skip-setup --skip-browser --non-interactive
