"""pandas を使った CLI サンプル。

小さな DataFrame を組み立てて整形表示するだけ。コンソールアプリなので
pyappdist 側は ``gui = false``（python.exe 起動）で配布する。
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
