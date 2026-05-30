# pyappdist 開発プラン

## Context
PROPOSAL.md で定義した「freeze しない Python アプリ配布ツール」を実装するための開発計画。
wheel 収集 → 専用 runtime へ正規 install → image 化 → launcher.exe → WiX MSI のパイプラインを、
Linux で検証可能な範囲を最大化しつつ、launcher と MSI のみ Windows CI に寄せて段階構築する。

## 確定方針
- ターゲット: Windows x64 / wheel only（MVP）。macOS/Linux・自動アップデータ・MSIX・複雑な CustomAction は対象外。
- launcher.exe: **image 内の python.exe / pythonw.exe をサブプロセス起動する薄い C スタブ**（C-API 埋め込みなし）。**C + MSVC（cl.exe）/ Windows CI（Microsoft 公式コンテナ）でビルド**、クロスしない。
- 設定スキーマ: `[tool.pyappdist]` + `launchers` 配列（複数 exe 対応）。
- venv 不使用。アプリと依存は runtime の `Lib\site-packages` へ正規 install（.pth も site が処理し importlib 互換）。
- MSI は CustomAction を使わず「コピー / ショートカット / レジストリ登録」のみ。
- 生成物はすべて `appdist/` 配下に出力（`appdist/wheelhouse/`・`appdist/runtime/`・`appdist/image/`・`appdist/dist/<name>.msi`・portable zip）。`appdist/` は作業ディレクトリとして .gitignore する。

## 設定スキーマ（pyproject.toml）
```toml
[tool.pyappdist]
name = "My App"
identifier = "com.example.myapp"
version = "1.0.0"
python = "3.12"            # 取得する runtime / wheelhouse の --python-version を駆動
target = "windows-x86_64"

[[tool.pyappdist.launchers]]
name = "myappcli"          # 出力 exe 名 (myappcli.exe)
entry = "myapp.__main__:main"  # module:callable 形式
gui = false                # true で windows サブシステム(コンソール非表示)
icon = "assets/myapp.ico"  # 任意
args = "--profile default" # 任意。固定引数(1 文字列)。空白区切りで子の argv に分割される

[tool.pyappdist.installer]
backend = "wix"
manufacturer = "Example Inc."
upgrade_code = "PUT-GUID-HERE"
```
※ sample/helloworld の現行 TOML は構文不正のため上記形式に修正する。

## モジュール構成（src/pyappdist/）
```
cli.py            # argparse サブコマンド (薄い層): build-wheels / fetch-runtime / build-image / gen-wix / build
config.py         # [tool.pyappdist] を tomllib で読み dataclass 化 + バリデーション (単一の真実)
errors.py         # 例外階層 (ConfigError, BuildError ...)
context.py        # BuildContext: 解決済みパス・config・作業ディレクトリ
wheels.py         # uv build / uv pip download → appdist/wheelhouse (--python-platform windows --only-binary :all:)
runtime.py        # python-build-standalone tarball の取得・展開・検証 → appdist/runtime (下記「fetch-runtime 仕様」)
image/
  layout.py       # appdist/ 出力レイアウト(wheelhouse/runtime/image/dist)の定数 (単一の真実)
  install.py      # pip install --no-index --find-links appdist/wheelhouse (runtime の Lib\site-packages へ) のラッパ
  compile.py      # compileall (-s でビルドパス除去)
  assemble.py     # runtime + site-packages を image/ に組み立て + portable zip
launcher/
  spec.py         # LauncherSpec: name/entry/gui/icon/args → 中立データ
  config_blob.py  # launcher へ渡す設定 (埋め込み or 追記) の生成
  build_inputs.py # Windows CI でビルドするための入力(.c は同梱資産, .rc/定数を生成)
wix/
  scan.py         # image を走査し File/Component の中立 IR を生成
  guid.py         # 安定 GUID = uuid5(upgrade_code, install相対パス)
  generate.py     # IR → WiX XML 文字列 (テンプレート, 純粋関数)
resources/        # launcher C ソース, WiX テンプレート断片を同梱
```

## launcher.exe 戦略（サブプロセス方式）
- **方式**: image 内 runtime の `python.exe`(console) / `pythonw.exe`(GUI) を `CreateProcess` で起動するだけの薄い C スタブ。C-API 埋め込みはしない。`cl.exe`(MSVC) でコンパイル、`rc.exe` で icon/version リソース、Windows CI（Microsoft 公式 build-tools コンテナ）でビルド。
- **なぜサブプロセス方式か**: pythonXX.dll の動的ロードや PyConfig/C-API のバージョン差異リスクが消え、スタブが極小・堅牢になる。Python バージョンが変わってもスタブは無改修。pythonw.exe が GUI(コンソール非表示)をネイティブに担う。
- **環境変数の流入防止（重要・二重防御）**:
  1. 起動時に必ず `-I`(isolated mode) を付与 → `-E`(全 `PYTHON*` 環境変数を無視: PYTHONHOME/PYTHONPATH/PYTHONSTARTUP/PYTHONUSERBASE 等) + `-s`(user site 無効) + 安全な sys.path を一括で得る。PROPOSAL の隔離要件を満たす。
  2. defense-in-depth として、スタブが `CreateProcess` に渡す環境ブロックから `PYTHON*` を除去する。
- **sys.path / home**: python-build-standalone は relocatable で、python.exe は自身の位置から home/stdlib を解決する。アプリと依存は runtime の `Lib\site-packages` へ install するため通常の site 処理で sys.path に載る(.pth も処理される)。launcher 側の path 注入は不要。
- **GUI/console**: console launcher = console サブシステムのスタブ → python.exe。GUI launcher = windows サブシステムのスタブ → pythonw.exe。スタブのサブシステムはビルド時に確定（コンソール点滅を防ぐ）。
- **アプリ差し替え（ビルド時埋め込み）**: 起動対象(python.exe/pythonw.exe)・起動指定(下記)・icon・version をビルド時に `.rc`/コンパイル定数へ。将来「同一 stub を複数 launcher で流用」する場合は exe 末尾への設定 blob 追記方式に拡張可。
- **起動指定**: `entry="module:callable"` は `-c "import sys; from <module> import <callable>; sys.exit(<callable>())"`。`-m` 相当が使える場合は `-m <module>`。
- **引数**: 固定引数 `args` は **単一文字列**。コマンドラインにそのまま連結し、子プロセスの argv パーサが空白で分割する(複数欲しければ `"arg1 arg2"` と書く)。続けてユーザー引数を付与。
- **exit code**: スタブは子を `WaitForSingleObject` し、`GetExitCodeProcess` を自身の exit code として返す。

## runtime 取得（fetch-runtime）仕様
python-build-standalone は uv と独立した安定仕様のプロジェクトで、URL は固定パターンで機械的に構成できる。

**入力**: config の `python`(例 `"3.12"` または `"3.12.13"`) と `target`(`"windows-x86_64"`)。任意で release 固定 `runtime_release`(例 `"20260310"`)・オフライン用 `runtime_source`(ローカル tar.gz パス)。
**target triple 対応**: `windows-x86_64` → `x86_64-pc-windows-msvc`（将来 `windows-arm64` → `aarch64-pc-windows-msvc`）。
**flavor**: `install_only_stripped`(既定・最小)。

**解決手順**:
1. `runtime_source`/同梱 tarball が `python`+`target` に一致すれば、それを使用(ネットワーク不要)。同梱 `cpython-3.12.13+20260310-x86_64-pc-windows-msvc-install_only_stripped.tar.gz` を既定のオフライン源にする。
2. release tag を決定: `runtime_release` 固定があれば使用。無ければ `https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json` を取得し `tag` と `asset_url_prefix` を得る。
3. `{asset_url_prefix}/SHA256SUMS` を取得し、`cpython-{python}.*-x86_64-pc-windows-msvc-install_only_stripped.tar.gz` に一致する資産を選択(minor 指定なら最大 patch)。これで **full version** と **sha256** を確定。
4. 資産名 = `cpython-{full_version}+{tag}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`、URL = `{asset_url_prefix}/{資産名}`(または CDN ミラー `https://releases.astral.sh/github/python-build-standalone/releases/download/{tag}/{資産名}`)。キャッシュ(`~/.cache/pyappdist/runtime/`)へ download し sha256 検証。一致キャッシュがあれば再 download しない。
5. install_only レイアウト(先頭 `python/`)を `appdist/runtime/` へ展開。
6. **検証**: `python/python.exe`・`python/python3XY.dll`(minor 一致)・`python/Lib` の存在。確定した full version を下流(wheelhouse の `--python-version`, launcher が起動する python.exe)へ伝播。

**冪等性**: `appdist/runtime/.pyappdist-runtime.json`(tag+version+sha 記録)で展開済みかつ一致ならスキップ。

## 開発環境（重要）
- WSL2 + **Windows ボリューム**上で作業しており、`.exe` 付きで Windows ツールチェーンを WSL から直接実行できる。**launcher ビルド・MSI を含む全工程をローカルで実機検証可能**（CI 必須ではない）。
- `uv.exe run python` … Windows uv(msvc) → Windows Python。`uv run`(無印) は Linux 版。
- MSVC … Visual Studio Community 2026 (VC.Tools.x86.x64)。`cl.exe`/`rc.exe` は PATH 外なので vswhere/vcvars で解決。
- `dotnet.exe` 10 … `dotnet tool install --global wix` で WiX をローカル取得。
- venv 運用: このディレクトリの `.venv` は **Linux 用**に固定（Linux/Windows で共有不可、lib64 シンボリックリンクで Windows uv がアクセス拒否）。Windows 用 venv が必要なときは作業用ディレクトリに環境をコピーして `uv.exe sync` で作成する。

## テスト/検証戦略（ローカル実機 + CI クリーンルーム）
1. **純ロジックの Linux TDD**: `config.py`・`wix/generate.py`(純粋関数) 等は Linux Python で高速 TDD。WiX XML はゴールデン比較 + スキーマ検証(Linux 完結, `wix build` は走らせない)。GUID 安定性を回帰テスト。
2. **ローカル Windows 実機 E2E（.exe ブリッジ）**: `uv.exe`/MSVC/WiX を使い、wheelhouse → runtime取得 → install(Windows python.exe) → launcher(cl.exe)ビルド → 実機起動 → `wix build` → MSI install→起動 までを**ローカルで実機検証**。sample/helloworld を E2E フィクスチャに「install → exe 起動 → 既知 stdout/exit code」「外部 PYTHON* を無視」を assert。CI を待たず反復。
3. **CI クリーンルーム確認**: GitHub Actions windows-latest（+ Microsoft コンテナ）で同 E2E を汚染なし環境で最終確認。リリース成果物はここで生成。
- 補助: install フローは Linux 版 python-build-standalone runtime でも OS 非依存に確認できる(早期検出用)。Wine は不採用。

## フェーズと完了条件
**Phase 0 — 基盤**
- requires-python を 3.11+ に引き上げ(tomllib stdlib のみ、依存ゼロ維持)。`packaging` を依存追加。cli.py に no-op サブコマンド骨組み。sample/helloworld の TOML を valid な launchers 配列に修正。
- 完了: `uv run pyappdist --help` がサブコマンド表示、CI(lint/test) グリーン。

**Phase 1 — wheelhouse + runtime 取得（Linux 完結）**
- wheels.py(uv build / uv pip download)、runtime.py(同梱 tarball 展開・検証)。
- 完了: `pyappdist build-wheels sample/helloworld` で `appdist/wheelhouse/*.whl`(app+deps) 生成。`fetch-runtime` で `appdist/runtime/` へ展開・検証。sdist-only 依存は明示エラー。

**Phase 2 — image 組み立て（Linux runtime で代替検証）★最初の動く価値**
- image/install.py・compile.py・layout.py・assemble.py。runtime の site-packages へ install + compileall + portable zip。
- 完了: `pyappdist build-image` が `appdist/image/` を生成し、Linux runtime での代替実行が helloworld の期待出力を返す。importlib.metadata で app バージョンが読める。

**Phase 3 — WiX XML 生成（Linux 完結, build は CI）**
- wix/scan.py・guid.py・generate.py。Product/Directory/Component/File/Shortcut/RegistryValue/Feature/MajorUpgrade。pyc も File 化(install 時生成しない)。
- 完了: 生成 XML がゴールデン一致 + スキーマ通過。Windows CI で `wix build` 成功(launcher 未完なら暫定 exe を File 化し構造のみ確認)。

**Phase 4 — launcher.exe（C+MSVC, サブプロセス方式）**
- launcher C stub、config_blob、build_inputs。`CreateProcess` で python.exe/pythonw.exe を `-I` + 起動指定 + 環境ブロックから PYTHON* 除去で起動、exit code 伝播。icon/version/gui-console をビルド時埋め込み。ビルドはローカル MSVC(cl.exe/rc.exe) で反復、CI でも同手順。
- 完了: helloworld 用 exe をローカル実機でビルド→image 内実行→期待 stdout/exit code。GUI モードで console 非表示。ユーザー args が反映。外部 PYTHON* 環境変数を設定しても無視されることを検証。複数 launchers 配列から複数 exe 生成。

**Phase 5 — E2E 統合 + 署名フック**
- `pyappdist build` で wheelhouse→runtime→image→(CI)launcher→wix→MSI を 1 コマンド。Windows CI で MSI install→起動スモーク。署名は未署名で出し、CI に署名ステップの hook のみ用意(証明書は secret)。
- 完了: タグ push で `appdist/dist/<name>.msi` + portable zip がリリース成果物として生成、windows-latest で install→起動が通る。

> image-only(portable zip) は Phase 2 完了時点で出荷可能。

## 技術選定
- TOML: requires-python を 3.11+ に上げ stdlib `tomllib` のみ(依存ゼロ)。
- `packaging`: wheel ファイル名/タグ/バージョン解析に依存追加。
- CLI: argparse(stdlib)。
- uv: subprocess 経由(`uv build`/`uv pip download`/`uv python`)。下限 0.11 を doc 化。
- launcher: C + MSVC(cl.exe) + rc.exe、Windows CI(Microsoft 公式コンテナ)。
- runtime: 同梱 tarball を一次ソース、無ければ astral リリース URL から取得・キャッシュ。

## リスク・未確定事項
- **entry vs -m の実行モデル**: sample は `entry="module:callable"`。`-c` ブートストラップで callable を呼ぶ方式に統一(PROPOSAL の -m 記述は entry 形式に寄せる)。
- **二プロセスモデル**: launcher.exe → python.exe の親子構成。プロセス一覧上の実体は python.exe。exit code は GetExitCodeProcess で伝播。単一プロセス identity が要件化した場合は将来 C-API 埋め込みへ切替可能(設計を `launcher/` 内に隔離)。
- **runtime site-packages へ install**: --target を使わず runtime 標準の site-packages へ入れるため .pth が site 処理で実行され importlib 互換性が高い。relocatable 前提が崩れる依存(絶対パス書込み等)は Linux runtime E2E で早期検出。
- **stable component GUID**: uuid5(upgrade_code, 相対パス) で決定的生成。Component=1 File 原則で KeyPath 単純化。
- **wheel only の現実性**: Windows wheel が無い依存は解決失敗 → wheels.py で明示エラー。
- **Python バージョン整合**: config.python から runtime 取得と wheelhouse の --python-version を駆動し不一致を検証で弾く(sample は 3.14 要求, 同梱 runtime は 3.12, PROPOSAL 例は 3.13 と現状バラバラ)。
- **署名**: MVP 未署名。SmartScreen 警告は既知制約として doc 化。
