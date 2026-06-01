# pyappdist macOS 対応プラン（実機 Mac 移行後の作業メモ）

## Context

Windows 向け（MSI / MSIX）が一通り揃ったので、次は macOS 配布物（`.app` / `.dmg` /
`.pkg`）に着手する。**macOS のコード署名・公証（notarization）は macOS 上でしか実行
できない**ため、開発環境を実機 Mac に移行する。本ドキュメントは移行後にゼロから迷わず
進めるための設計・手順・参考資料のまとめ。

既存の中核思想（freeze せず、専用 Python ランタイムへ正規 install してそのまま同梱）は
macOS でもそのまま通用する。変わるのは「パッケージング形式」と「署名/公証が必須・有料・
Mac 専用」という点。

## なぜ WSL ワークフローが使えないか（前提の変化）

- `codesign` / `productbuild` / `pkgbuild` / `hdiutil` / `xcrun notarytool` / `iconutil` は
  **macOS 専用**。Windows の `wix.exe`/`makeappx.exe` を WSL interop で叩く中核トリックが
  通用しない。→ **ビルド・署名・公証・実機検証はすべて Mac 上でネイティブに行う。**
- クロスビルドは原則しない（arm64 Mac で macos-arm64 をネイティブにビルド）。

## 0. Mac 環境セットアップ（最初にやる）

1. **Xcode Command Line Tools**: `xcode-select --install`（`codesign`/`clang` 等）。
   `notarytool`/`stapler` は `xcrun` 経由（Xcode 13+ 相当）。
2. **Apple Developer Program 登録（$99/年・有料）** — Developer ID 証明書と公証に必須。
   ※ Windows の MS ストア無料化とは違い macOS は有料。
3. **証明書**（developer.apple.com / Xcode で作成し login keychain に入れる）:
   - **Developer ID Application** … `.app`/`.dmg`（ストア外配布）の署名用。
   - **Developer ID Installer** … `.pkg` の署名用。
4. **公証クレデンシャル**: App用パスワード（appleid.apple.com）か App Store Connect API キーを
   `xcrun notarytool store-credentials <profile> --apple-id ... --team-id ... --password ...`
   で keychain プロファイル化（以降 `--keychain-profile <profile>` で使う）。
5. **uv / リポジトリ clone / python-build-standalone の macOS ランタイム取得**確認。
6. 確認: `codesign`, `xcrun notarytool`, `xcrun stapler`, `hdiutil`, `pkgbuild`,
   `productbuild`, `iconutil`, `spctl` が叩けること。

## 1. ターゲット / 設定スキーマ設計

`[[tool.pyappdist.targets]]` 配列はそのまま流用し、macOS 用の platform と format を足す。

- **platform 追加**（`targets.py`）: `macos-arm64`（triple `aarch64-apple-darwin`）、
  `macos-x86_64`（triple `x86_64-apple-darwin`）。`Target.wix_arch` は Windows 専用なので、
  汎用 `arch` か macOS 用フィールドに整理する（あるいは os 別に分岐）。
- **format 追加**: `app`（素の `.app`、zip 配布向け）/ `dmg`（ディスクイメージ、既定候補）/
  `pkg`（インストーラ）。
- **`identifier`（CFBundleIdentifier, 逆DNS）を復活**。Windows では未使用で削除したが、
  **macOS のバンドル/署名/公証では必須**。app レベル（`[tool.pyappdist].identifier`）が自然。
- **macOS 用ターゲットキー（案）**: `signing_identity`（"Developer ID Application: Name (TEAMID)"）、
  `team_id`、`notary_profile`（keychain プロファイル名）、`entitlements`（plist パス、既定は
  内蔵テンプレート）、`category`（LSApplicationCategoryType）、`min_macos`（LSMinimumSystemVersion）。
  署名/公証は環境依存なので、CI/手元の差を吸収できるよう env 上書き（例 `PYAPPDIST_NOTARY_PROFILE`）も。

## 2. パイプライン統合（既存ステージの再利用と差分）

| ステージ | 既存(Windows) | macOS での差分 |
|---|---|---|
| runtime | `runtime.py`（platform 駆動で取得・展開） | macOS triple を取得。`install_only` flavor 有。**framework/シンボリックリンク**を保つ展開に注意（DrvFs 回避フィルタは不要、逆に symlink/権限を保持）。 |
| wheels | ターゲット python で `pip wheel` | Mac ではターゲット＝ネイティブ python。C 拡張はネイティブビルド。**arch 整合**（arm64 上で arm64 wheel）。 |
| image | runtime+install を `image/` に | レイアウトが `.app` 構造になる（下記）。`python/` を `Contents/Resources/` 等へ。 |
| launcher | `launcher.c`＋MSVC で `<name>.exe` | **macOS 用 launcher を新規**: `Contents/MacOS/<name>`（Mach-O）。clang でビルドする薄い C スタブが署名上も無難（CFBundleExecutable に指定。shell script だと hardened runtime/署名で扱いにくい）。同梱 python を `-I` 起動＋entry bootstrap は Windows 版の考え方を流用。 |
| package | `wix`/`msix` | **新規 `macos/` モジュール**: `.app` 組み立て → `dmg`(hdiutil) or `pkg`(pkgbuild/productbuild) → **codesign（deep）→ notarytool → stapler**。 |

## 3. `.app` バンドル構造

```
MyApp.app/
  Contents/
    Info.plist                 # CFBundleIdentifier / Name / Executable / Version / Icon / LSMinimumSystemVersion 等
    MacOS/<launcher>           # Mach-O（CFBundleExecutable）
    Resources/
      python/ …                # 同梱ランタイム＋install 済みアプリ
      AppIcon.icns
    _CodeSignature/            # 署名後に生成
```

Info.plist 主要キー: `CFBundleIdentifier`(=identifier), `CFBundleName`, `CFBundleExecutable`,
`CFBundleVersion`/`CFBundleShortVersionString`, `CFBundleIconFile`, `LSMinimumSystemVersion`,
`NSHighResolutionCapable=true`, `LSApplicationCategoryType`。

## 4. 署名＆公証（必須・最大の難所）

1. **deep 署名（順序が重要）**: バンドル内の **すべての Mach-O**（同梱 python 本体、
   `site-packages` の全 `.so`、launcher、dylib）を **Developer ID Application** 証明書＋
   **hardened runtime**（`codesign --options runtime`）＋**entitlements** で**内側から先に**署名し、
   最後に `.app` 本体を署名する（`--deep` は非推奨。個別署名 → 親署名の順が安全）。
2. **entitlements（Python 同梱の肝）**: hardened runtime 下で同梱 python が `.so`/dylib を
   ロードできるよう、最小限を見極める。よく使う候補:
   `com.apple.security.cs.allow-jit`、`com.apple.security.cs.allow-unsigned-executable-memory`、
   `com.apple.security.cs.disable-library-validation`（自/他署名の .so ロード許可）。
   まず全部入りで通し、後で絞る。
3. **公証**: `.dmg`/`.pkg`（または zip）を `xcrun notarytool submit --keychain-profile <p> --wait` →
   成功後 `xcrun stapler staple MyApp.app`（or dmg/pkg）。
4. **検証**: `codesign --verify --deep --strict --verbose=2 MyApp.app`、
   `spctl -a -t exec -vvv MyApp.app`（Gatekeeper 判定）、pkg は `spctl -a -t install`。

> 未署名/未公証は Gatekeeper でブロック（Apple Silicon は未署名ネイティブコードがそもそも
> 動かない）。MSI の「未署名でも警告で押し切れる」は通用しない。

## 5. アイコン（.icns）

macOS は `.icns`（`.ico` 不可）。`logo`/icon の元 PNG から `iconutil`（要 iconset の各サイズ PNG、
`sips` でリサイズ生成）で `.icns` を作る。Windows のロゴ処理（単一PNG→各サイズ）に近い発想で実装。

## 6. アーキテクチャ

- `arm64` / `x86_64` / **universal2**。python-build-standalone は両アーチ＋universal2 あり。
  まずは**ネイティブ単一アーチ**（手元 Mac のアーチ）でMVP、必要なら universal2 / 別アーチ追加。

## 7. 実装順チェックリスト（移行後）

1. Mac 環境（§0）: CLT・Apple Developer・証明書・notary プロファイル。
2. `targets.py`: macOS platform 追加、`arch` 整理。`identifier`（bundle id）復活。
3. config: macOS ターゲットキー（signing_identity/team_id/notary_profile/entitlements/min_macos/category）。
4. `runtime.py`: macOS ランタイム取得・展開（symlink/権限保持）を検証。
5. image/launcher: `.app` レイアウトと macOS launcher（clang スタブ）を設計・実装。
6. `macos/bundle.py`: `.app` 組み立て＋Info.plist＋`.icns`。
7. `macos/sign.py`: deep codesign（hardened runtime＋entitlements、内→外順）。
8. `macos/notarize.py`: `notarytool submit --wait` ＋ `stapler staple`。
9. `macos/package.py`: `dmg`(hdiutil) / `pkg`(pkgbuild+productbuild)。
10. `cli.py`: format 分岐に `app`/`dmg`/`pkg` 追加。
11. e2e: macOS smoke ターゲット。`spctl` が公証後に通ることまで確認。
12. docs（configuration/cli/installation）更新、CLAUDE.md・メモリ追記。

## 8. 参考資料

- **python-build-standalone** リリース（macOS triples `aarch64/x86_64-apple-darwin`、`install_only`）:
  https://github.com/astral-sh/python-build-standalone
- Apple「Notarizing macOS software before distribution」/「Customizing the notarization workflow」
  （`notarytool`/`stapler`）, 「Signing your apps for Gatekeeper」, `man codesign`,
  Hardened Runtime entitlements 一覧, Bundle / Info.plist Key リファレンス。
- `iconutil`/`sips`（.icns 生成）。
- **先行ツールを“設計の教科書”として読む**（Python 同梱 .app＋署名＋公証の実装例）:
  - **BeeWare Briefcase** — まさに「Python＋依存を .app 化し codesign/notarize」する。entitlements
    セットや署名順、dmg 化が最も参考になる。
  - py2app / PyInstaller(macOS) / dmgbuild — `.app` レイアウト・dmg 作成・署名スクリプトの実例。

## 9. Windows との差分まとめ

- `identifier`（bundle id）復活（必須）。
- 署名・公証が**必須・有料（$99/年）・Mac 専用**。WSL interop は使えずネイティブ実行。
- launcher は MSVC ではなく clang ビルドの Mach-O スタブ。
- アイコンは `.icns`（`.ico` 不可）。
- Mac App Store 配布は別物（sandbox＋App Store 証明書＋Transporter）＝当面スコープ外。
