"""pandas-based CLI sample.

Builds a small DataFrame and prints it. It is a console app, so pyappdist
ships it with ``gui = false`` (launched via python.exe).
"""

from __future__ import annotations

import pandas as pd


def main() -> int:
    df = pd.DataFrame(
        {
            "name": ["alice", "bob", "carol"],
            "score": [90, 75, 88],
        }
    )
    df["grade"] = pd.cut(df["score"], bins=[0, 80, 100], labels=["B", "A"])
    print(df.to_string(index=False))
    print(f"\npandas {pd.__version__} / mean score = {df['score'].mean():.1f}")
    return 0
