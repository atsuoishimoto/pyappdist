"""matplotlib を使った GUI サンプル。

sin / cos のグラフをウィンドウに描画する。バックエンドは TkAgg を使う
（tkinter は python-build-standalone の runtime に同梱されているので追加依存が要らない）。
GUI アプリなので pyappdist 側は ``gui = true``（pythonw.exe 起動）で配布する。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("TkAgg")  # 追加の GUI 依存なしで動く（runtime 同梱の tkinter）

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402  (matplotlib が numpy を持ち込む)


def main() -> int:
    x = np.linspace(0, 2 * np.pi, 400)
    fig, ax = plt.subplots()
    ax.plot(x, np.sin(x), label="sin")
    ax.plot(x, np.cos(x), label="cos")
    ax.set_title("pyappdist + matplotlib")
    ax.set_xlabel("x")
    ax.legend()
    fig.tight_layout()
    plt.show()
    return 0
