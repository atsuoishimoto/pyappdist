# pyside6demo

pyappdist の GUI サンプル。PySide6（Qt）でウィンドウを表示する。
`gui = true` の launcher なので、配布物では `pythonw.exe` 起動（コンソール非表示）になる。

PySide6 のような大きな C 拡張つき依存（abi3 wheel: `cp39-abi3-win_amd64`）でも
cp312 ランタイムへ収集・install できることを確認するサンプルでもある。

## 配布物を作る

```bash
pyappdist build sample/pyside6demo
```
