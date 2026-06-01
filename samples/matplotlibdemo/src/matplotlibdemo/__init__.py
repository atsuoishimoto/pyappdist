"""matplotlib-based GUI sample.

Draws sin / cos curves in a window using the TkAgg backend (tkinter ships with
the python-build-standalone runtime, so no extra dependency is needed). It is a
GUI app, so pyappdist ships it with ``gui = true`` (launched via pythonw.exe).
"""

from __future__ import annotations

import matplotlib

matplotlib.use("TkAgg")  # works with no extra GUI dependency (runtime-bundled tkinter)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402  (matplotlib pulls in numpy)


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
