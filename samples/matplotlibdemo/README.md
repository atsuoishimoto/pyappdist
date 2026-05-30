# matplotlibdemo

pyappdist の GUI サンプル。matplotlib で sin / cos のグラフをウィンドウ表示する。
`gui = true` の launcher なので、配布物では `pythonw.exe` 起動（コンソール非表示）になる。

バックエンドは **TkAgg**。tkinter / tcl-tk は python-build-standalone の runtime に
同梱されているため、Qt 等の追加 GUI 依存なしで動く。matplotlib が持ち込む numpy 等の
C 拡張つき依存が Windows wheel として収集・install されることも確認するサンプル。

## 配布物を作る

```bash
pyappdist build sample/matplotlibdemo
```
