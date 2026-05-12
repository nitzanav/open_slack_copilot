#!/usr/bin/env bash
# Symlink repo skill_examples/* into ~/.open_slack_copilot/skills mirroring paths.
# Skips any destination path that already exists (file, directory, or symlink).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
skill_examples="${repo_root}/skill_examples"
dest="${HOME}/.open_slack_copilot/skills"

if [[ ! -d "${skill_examples}" ]]; then
  echo "error: missing ${skill_examples}" >&2
  exit 1
fi

mkdir -p "${dest}"

# Each directory that contains SKILL.md is one installable skill.
while IFS= read -r -d '' skill_md; do
  skill_dir="$(dirname "${skill_md}")"
  rel="${skill_dir#"${skill_examples}"/}"
  if [[ -z "${rel}" ]]; then
    continue
  fi
  target="${dest}/${rel}"
  if [[ -e "${target}" || -L "${target}" ]]; then
    echo "skip (exists): ${target}"
    continue
  fi
  mkdir -p "$(dirname "${target}")"
  ln -s "${skill_dir}" "${target}"
  echo "linked: ${target} -> ${skill_dir}"
done < <(find "${skill_examples}" -name SKILL.md -print0)
