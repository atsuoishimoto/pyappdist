# pandascli

pyappdist の CLI サンプル。pandas（C 拡張 + numpy 依存）で小さな DataFrame を
整形表示する。`gui = false` の launcher なので、配布物では `python.exe` 起動
（コンソール表示）になる。

pandas / numpy のような C 拡張つき依存が Windows wheel として収集され、
runtime の site-packages へ install されることを確認するサンプルでもある。

## 配布物を作る

```bash
pyappdist build sample/pandascli
```
