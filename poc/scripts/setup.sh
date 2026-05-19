#!/usr/bin/env bash
# PoC setup — pygame-ce 설치 + snake.py 정상 동작 검증.
#
# Spec ref: docs/design/02-설계문서.md §10.4.
#
# pygame (mainline) 은 Python 3.14 휠이 아직 없어 sdl2-config 빌드 필요.
# pygame-ce (community edition) 는 Python 3.14 cp314 manylinux 휠 제공 →
# import pygame 그대로 호환. 본 PoC 는 pygame-ce 사용.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${VIRTUAL_ENV:-}" ]] && [[ -d "$REPO_ROOT/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.venv/bin/activate"
fi

echo "[setup] python: $(python --version)"

echo "[setup] installing pygame-ce + pyyaml"
pip install --quiet "pygame-ce>=2.5" "pyyaml>=6.0"

echo "[setup] verifying snake.py headless run"
SDL_VIDEODRIVER=dummy python poc/targets/snake-game/original/snake.py \
  --headless --auto-play 2

echo "[setup] OK"
