"""Minimal pygame-ce GUI sample.

A ball bounces around inside a window. Close the window or press ESC to quit.
It is a GUI app, so pyappdist ships it with ``gui = true`` (launched via pythonw.exe).
"""

from __future__ import annotations

import pygame

WIDTH, HEIGHT = 480, 320
RADIUS = 24
BG = (30, 30, 46)
BALL = (137, 220, 235)
TEXT = (205, 214, 244)


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("pyappdist + pygame-ce")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 32)
    label = font.render("pyappdist + pygame-ce", True, TEXT)

    x, y = WIDTH // 2, HEIGHT // 2
    vx, vy = 4, 3

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        x += vx
        y += vy
        if x - RADIUS <= 0 or x + RADIUS >= WIDTH:
            vx = -vx
        if y - RADIUS <= 0 or y + RADIUS >= HEIGHT:
            vy = -vy

        screen.fill(BG)
        pygame.draw.circle(screen, BALL, (x, y), RADIUS)
        screen.blit(label, (24, 16))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    return 0

if __name__ == '__main__':
    main()
