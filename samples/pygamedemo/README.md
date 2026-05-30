# pygamedemo

pyappdist の GUI サンプル。pygame-ce（C 拡張を含む依存）でウィンドウを開き、
ボールが跳ね回る。ウィンドウを閉じるか ESC で終了する。

`gui = true` の launcher なので、配布物では `pythonw.exe` 起動（コンソール非表示）になる。
pygame-ce のような C 拡張つき依存が wheelhouse（Windows wheel）として収集され、
runtime の site-packages へ install されることを確認するサンプルでもある。

## 配布物を作る

```bash
pyappdist build sample/pygamedemo
```

`sample/pygamedemo/appdist/` に image / portable zip / MSI が出力される。
