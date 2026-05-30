
# pyappdist


## 概要

pyappdist は Python アプリケーションを Windows 向け配布物へ変換するツールである。

既存の freeze 型ツールのように Python アプリを exe 化しない。

代わりに、

* Python Runtime
* 正規 install 済み site-packages
* アプリ専用 launcher.exe
* WiX 生成 MSI

を組み合わせて、通常の Python 環境に近い配布イメージを作成する。

---

# 基本方針

## Freezeしない

PyInstaller や Nuitka のように、Pythonコードを実行ファイルへ固めない。

```text
Python source
  ↓
wheel
  ↓
runtime image
  ↓
MSI
```

## Wheel First

アプリ本体は wheel としてビルドする。

依存関係も wheel として収集する。

```text
dist/myapp.whl
wheelhouse/*.whl
```

## Installしてから固める

wheel を単に展開しない。

専用 Python runtime に対して正規の install を行い、完成済み image を作る。

```text
wheelhouse
  ↓
pip install / installer install
  ↓
site-packages
  ↓
image
```

これにより、

* importlib.metadata
* importlib.resources
* package data
* dist-info
* entry points
* .pth

との互換性を保つ。

---

# Windows MVP

## 成果物

まずは以下の2種類を作る。

```text
image/
dist/MyApp.msi
```

`image/` は portable 実行ディレクトリとしても利用できる。

`MyApp.msi` は image を Program Files にコピーするだけの MSI である。

---

# ビルドフロー

## 1. アプリ wheel を作成

```bash
uv build
```

成果物:

```text
dist/myapp-1.0.0-py3-none-any.whl
```

## 2. Windows向け wheelhouse を作成

wheel only 前提で、Windows ターゲット向けに解決する。

```bash
uv pip compile pyproject.toml \
  --python-platform windows \
  --only-binary :all: \
  -o requirements-windows.txt
```

```bash
uv pip download \
  --python-platform windows \
  --only-binary :all: \
  --dest wheelhouse \
  -r requirements-windows.txt
```

アプリ本体 wheel も wheelhouse に追加する。

```text
wheelhouse/
  myapp-1.0.0-py3-none-any.whl
  dependency1.whl
  dependency2.whl
```

## 3. Windows用 Python runtime を取得

python-build-standalone の Windows x64 runtime を取得する。

Linux CI でも Windows 用 runtime を取得できる。

```text
python-build-standalone
  ↓
windows-x86_64 runtime
```

## 4. Runtime image を作成

```text
image/
├─ MyApp.exe
├─ python/
├─ Lib/
├─ site-packages/
└─ resources/
```

venv は使用しない。

理由:

* venv は relocatable ではない
* インストール先パスに依存する
* アプリ専用 runtime なので venv を分ける意味が薄い

## 5. wheel を runtime に install

専用 Python runtime へ直接 install する。

```bash
image/python/python.exe -m pip install \
  --no-index \
  --find-links wheelhouse \
  --target image/site-packages \
  myapp
```

または、runtime の site-packages を通常配置にして install する。

```bash
image/python/python.exe -m pip install \
  --no-index \
  --find-links wheelhouse \
  myapp
```

最終的に launcher が参照する `sys.path` は pyappdist が明示的に制御する。

## 6. pyc を生成

ビルド時に `.pyc` を生成する。

```bash
image/python/python.exe -m compileall image/site-packages
```

ビルドマシンの絶対パスを残さないよう、必要に応じて `compileall -s/-p` または `-d` を使う。

## 7. launcher.exe を生成

ランチャーは Python DLL をロードし、`pythonw.exe -m module` 相当を実行する。

```text
MyApp.exe
  ↓
python313.dll
  ↓
-m myapp
```

ランチャーはアプリごとに以下だけ差し替える。

* アイコン
* バージョン情報
* アプリ名
* 起動 module
* GUI / console mode
* 固定 args
* 署名

## 8. WiX XML を生成

pyappdist が image を走査し、WiX XML を自動生成する。

人間は WiX を直接書かない。

MSIの役割は限定する。

```text
Program Files\MyApp へ image をコピー
スタートメニューショートカット作成
アンインストール登録
```

インストール後に pip install は行わない。

## 9. GitHub Actions Windows runner で MSI 作成

WiX は Windows runner 上で動かす。

```yaml
runs-on: windows-latest

steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-dotnet@v4
    with:
      dotnet-version: '8.0.x'

  - name: Install WiX
    run: dotnet tool install --global wix

  - name: Build MSI
    run: wix build installer.wxs -o dist/MyApp.msi
```

---

# ランチャー仕様

## 目的

アプリ利用者に Python を意識させない。

```text
MyApp.exe
```

を実行すると、

```text
python -m myapp
```

相当が専用 runtime 上で実行される。

## Isolation

外部 Python 環境の影響を受けない。

無効化対象:

```text
PYTHONHOME
PYTHONPATH
PYTHONUSERBASE
PYTHONSTARTUP
```

PyConfig を使用する。

```text
isolated = true
use_environment = false
```

## sys.path

launcher が image 内の runtime と site-packages のみを参照する。

```text
image/python
image/site-packages
```

## 引数

固定引数とユーザー引数を結合する。

```toml
[tool.pyappdist]
launchers = [
  {name: "myappw", entry: "myapp:winmain", gui:true}, 
  {name: "myapp", entry: "myapp:main"}, 
]
```

実行:

```text
MyApp.exe file.txt
```

内部:

```text
python -m myapp --profile default file.txt
```

---

# pyproject.toml 例

```toml
[project]
name = "myapp"
version = "1.0.0"

[project.scripts]
myapp = "myapp.__main__:main"

[tool.pyappdist]
name = "My App"
identifier = "com.example.myapp"
version = "1.0.0"
python = "3.13"
target = "windows-x86_64"

[tool.pyappdist.launcher]
module = "myapp"
gui = true
icon = "assets/myapp.ico"
args = []

[tool.pyappdist.installer]
backend = "wix"
manufacturer = "Example Inc."
upgrade_code = "PUT-GUID-HERE"
```

---

# WiX方針

## WiXはテンプレ生成対象

WiXの複雑さを利用者に見せない。

pyappdist が以下を生成する。

* Product / Package
* MajorUpgrade
* Directory
* Component
* File
* Shortcut
* RegistryValue
* Feature

## インストール時処理を避ける

MSIの CustomAction は原則使わない。

```text
良い:
  ファイルコピー
  ショートカット
  レジストリ登録

避ける:
  pip install
  venv作成
  動的依存解決
```

これにより MSI は単純で壊れにくくなる。

---

# CI設計

## Linux job

可能な処理:

```text
wheel build
wheelhouse作成
Windows runtime取得
launcherクロスビルド
image作成
portable zip作成
```

## Windows job

Windows runner で行う処理:

```text
WiX install
WiX build
MSI署名
```

MSI生成だけ Windows に寄せる。

---

# Pynsistとの差分

Pynsist は wheel を取得して展開し、`pkgs/` を import path に追加する方式に近い。

pyappdist は wheel を正規 install してから image 化する。

```text
Pynsist:
  wheel unzip
  pkgs/ を sys.path に追加

pyappdist:
  pip install / installer install
  完成済み site-packages
  image化
```

pyappdist は以下の互換性を重視する。

* importlib.metadata
* importlib.resources
* package data
* dist-info
* .pth
* entry points

---

# Inno Setup / NSIS を使わない理由

## Inno Setup

便利だが、商用利用時のライセンス方針が気になる。

## NSIS

柔軟だが、GUIインストーラをスクリプトで扱う必要がある。

## WiX

MSI生成に特化できる。

pyappdist では人間が WiX を書かず、テンプレから自動生成するため扱いやすい。

---

# MVPスコープ

## 対応するもの

* Windows x64
* wheel only
* python-build-standalone runtime
* runtime image 作成
* launcher.exe
* portable zip
* WiX MSI

## 対応しないもの

* 複雑なMSI CustomAction
* macOS/Linux
* 自動アップデータ
* Microsoft Store / MSIX




```
❯ uv.exe python install 3.12 -v 2>&1 | grep -i download
DEBUG Found download `cpython-3.12.13-windows-x86_64-none` for request `3.12 (cpython-3.12-windows-x86_64-none)`
DEBUG Downloading https://releases.astral.sh/github/python-build-standalone/releases/download/20260310/cpython-3.12.13%2B20260310-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
Downloading cpython-3.12.13-windows-x86_64-none (download) (20.8MiB)
 Downloaded cpython-3.12.13-windows-x86_64-none (download)

 ```