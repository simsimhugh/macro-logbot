# Snake (PoC target)

MIT 라이선스로 본 repo 안에서 자체 작성한 minimal Pygame Snake (~200 LOC).
사내 mirror 환경에서도 추가 외부 clone 없이 동작하도록 외부 OSS 의존을 차단했다.

## 실행

```bash
# headless (CI/PoC 자동 측정)
SDL_VIDEODRIVER=dummy python original/snake.py --headless --auto-play 5

# 단축 — --headless 가 SDL_VIDEODRIVER 도 설정.
python original/snake.py --headless --auto-play 5
```

옵션:
- `--headless`: `SDL_VIDEODRIVER=dummy` (GUI 비활성).
- `--auto-play <초>`: 결정론 입력 (seed=42) 으로 N 초 자동 진행. 정상 코드에서 exit 0.

## 결정론 입력

`auto_play_actions(seed, num_ticks)` 가 `random.Random(seed)` 로 동일 시퀀스를 생성. 같은 인풋이면 같은 결과 (에러 주입 case 의 재현성 보장).

## 의존성

- `pygame-ce>=2.5` (Python 3.14 cp314 manylinux 휠 제공 — `import pygame` 그대로 호환).
- pygame mainline 은 Python 3.14 휠 미제공 — `poc/scripts/ops/setup.sh` 가 pygame-ce 설치.

## 라이선스

MIT — 본 디렉토리 `LICENSE` 참조.
