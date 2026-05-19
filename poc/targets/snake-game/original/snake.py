"""Minimal Pygame Snake — PoC target (MIT, ~200 LOC).

Spec ref: docs/design/02-설계문서.md §10.4 "Pygame Snake (MIT 클론, ~200줄,
SDL_VIDEODRIVER=dummy headless 실행)".

Headless 자동 실행:
    SDL_VIDEODRIVER=dummy python snake.py --headless --auto-play 5

--auto-play <seconds> 모드는 결정론적 입력 시퀀스 (seed=42) 로 같은 입력
시 같은 에러가 재현되도록 한다. 정상 코드에서 5 초 auto-play 는 exit 0
종료 (충돌 미발생 또는 결정 가능 종료).
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

# 결정론적 입력 — seed 고정. error_catalog 의 모든 case 가 같은 입력 시퀀스를
# 가정하므로 변경 시 모든 yaml 의 라인/트리거 영향.
DETERMINISTIC_SEED = 42

GRID_WIDTH = 20
GRID_HEIGHT = 15
CELL_SIZE = 20
FPS = 30

# direction dict — KeyError(E005) 주입 지점에서 사용.
DIRECTIONS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}


class Segment:
    """Snake body 의 한 칸."""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


class SnakeGame:
    """Grid-based Snake — head + body + food + score."""

    def __init__(self, seed: int = DETERMINISTIC_SEED) -> None:
        self.rng = random.Random(seed)
        self.head: Segment | None = None
        self.body: list[Segment] = []
        self.direction: str = "RIGHT"
        self.food: tuple[int, int] = (0, 0)
        self.score: int = 0
        self.alive: bool = True
        self.ticks: int = 0

    def init_game(self) -> None:
        """게임 상태 초기화 — head 및 body 배치, 첫 food spawn."""
        self.head = Segment(GRID_WIDTH // 2, GRID_HEIGHT // 2)
        self.body = [Segment(self.head.x - 1, self.head.y)]
        self.direction = "RIGHT"
        self.score = 0
        self.alive = True
        self.ticks = 0
        self.spawn_food()

    def spawn_food(self) -> None:
        """랜덤 빈 셀에 food 위치 설정."""
        while True:
            fx = self.rng.randint(0, GRID_WIDTH - 1)
            fy = self.rng.randint(0, GRID_HEIGHT - 1)
            if not self.occupies(fx, fy):
                self.food = (fx, fy)
                return

    def occupies(self, x: int, y: int) -> bool:
        """(x, y) 에 snake body 가 점유하는지."""
        if self.head is not None and self.head.x == x and self.head.y == y:
            return True
        return any(seg.x == x and seg.y == y for seg in self.body)

    def update_position(self) -> None:
        """방향에 따라 head 와 body 를 한 칸 이동."""
        dx, dy = DIRECTIONS[self.direction]
        new_x = self.head.x + dx
        new_y = self.head.y + dy
        # body 는 마지막을 떼어 head 자리에 넣는 방식 (간단 구현).
        self.body.insert(0, Segment(self.head.x, self.head.y))
        self.body.pop()
        self.head.x = new_x
        self.head.y = new_y

    def detect_collision(self) -> bool:
        """벽 또는 자기 몸 충돌 감지. True 면 죽음."""
        # 벽 충돌 — head 좌표가 grid 범위 벗어나면 충돌.
        if self.head.x < 0 or self.head.x >= GRID_WIDTH:
            return True
        if self.head.y < 0 or self.head.y >= GRID_HEIGHT:
            return True
        # body 충돌.
        for seg in self.body:
            if seg.x == self.head.x and seg.y == self.head.y:
                return True
        return False

    def detect_food(self) -> None:
        """head 가 food 위치에 도달하면 score++ 와 body 1 칸 확장."""
        if self.head.x == self.food[0] and self.head.y == self.food[1]:
            self.score = self.score + 1
            # body 확장 — 꼬리 위치 복제.
            tail = self.body[-1] if self.body else self.head
            self.body.append(Segment(tail.x, tail.y))
            self.spawn_food()

    def render_status(self) -> str:
        """score line — UI/log 둘 다에서 사용."""
        return "score: " + str(self.score)

    def step(self, action: str) -> None:
        """한 tick 진행. action: UP/DOWN/LEFT/RIGHT."""
        if not self.alive:
            return
        # 반대 방향 입력 무시 (전형적 snake rule).
        opposite = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
        if action != opposite.get(self.direction):
            self.direction = action
        self.update_position()
        if self.detect_collision():
            self.alive = False
            return
        self.detect_food()
        self.ticks += 1


def auto_play_actions(seed: int, num_ticks: int) -> list[str]:
    """결정론적 action sequence 생성. 같은 seed → 같은 시퀀스."""
    rng = random.Random(seed)
    keys = ["UP", "DOWN", "LEFT", "RIGHT"]
    return [rng.choice(keys) for _ in range(num_ticks)]


def run_headless(auto_play_seconds: float) -> int:
    """Headless 자동 실행 — pygame 화면 없이 game loop 만 돌린다.

    auto_play_seconds 동안 결정론적 action 시퀀스로 step.
    충돌(alive=False) 또는 시간 종료 시 return 0.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    pygame.init()
    game = SnakeGame()
    game.init_game()
    num_ticks = int(auto_play_seconds * FPS)
    actions = auto_play_actions(DETERMINISTIC_SEED, num_ticks)
    start = time.monotonic()
    for action in actions:
        if not game.alive:
            break
        game.step(action)
        if time.monotonic() - start > auto_play_seconds + 5:
            break
    print(game.render_status())
    pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minimal Pygame Snake (PoC target).")
    parser.add_argument("--headless", action="store_true", help="SDL_VIDEODRIVER=dummy")
    parser.add_argument(
        "--auto-play",
        type=float,
        default=5.0,
        help="auto-play seconds with deterministic input (default 5).",
    )
    args = parser.parse_args(argv)
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    return run_headless(args.auto_play)


if __name__ == "__main__":
    sys.exit(main())
