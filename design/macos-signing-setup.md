# macOS 署名・公証のセットアップ手順（証明書取得）

Developer ID 署名＋公証で配布可能な `.app`/`.dmg` を作るための、**一度だけ**やる準備の手順書。
コードは準備済みで、証明書と notary プロファイルが揃えば設定／環境変数を足してビルドするだけ
（ビルド・検証コマンドは `docs/signing.rst` の "Verifying a signed + notarized build" を参照）。

> ad-hoc 署名（既定）は Apple アカウント不要でローカル起動可。ただし他Macでは Gatekeeper に
> 弾かれる。配布するには以下の Developer ID + 公証が必須（有料・Mac専用・ネイティブ実行）。

---

## 0. 前提

- **Apple Developer Program 登録（$99/年）** 済みであること。
- **Xcode Command Line Tools**: `xcode-select --install`（`codesign`/`notarytool`/`stapler`）。
- 確認: `xcrun notarytool --version` / `xcrun stapler --help` が動くこと。

---

## 1. Developer ID 証明書の作成

配布物の種類で必要な証明書が違う。当面 `.app`/`.dmg` なら **Developer ID Application** だけでよい。

| 証明書 | 用途 | pyappdist での必要性 |
|---|---|---|
| **Developer ID Application** | `.app` / `.dmg`（ストア外配布）の署名 | **必須**（今のMVP対象） |
| **Developer ID Installer** | `.pkg` の署名 | `pkg` 形式対応時（後続） |

作成方法は2通り。**Xcode が楽**。

### 方法A: Xcode（推奨）

1. Xcode → Settings → **Accounts** で Apple ID を追加（Developer Program のアカウント）。
2. 対象の Team を選択 → **Manage Certificates…**。
3. 左下の **+** → **Developer ID Application** を作成。
   - （`.pkg` も視野に入れるなら **Developer ID Installer** も同様に作成）
4. 自動で login keychain に秘密鍵つきで入る。

### 方法B: developer.apple.com（CSR を手動作成）

1. **Keychain Access** → メニュー Certificate Assistant → **Request a Certificate From a
   Certificate Authority…**
   - Email を入力、**Saved to disk** を選択して `CertificateSigningRequest.certSigningRequest`
     を保存（"CA Email Address" は空でよい）。
2. <https://developer.apple.com/account/resources/certificates/list> → **+** →
   **Developer ID Application** → さきほどの CSR をアップロード。
3. 発行された `developerID_application.cer` をダウンロードしてダブルクリック → login keychain に
   インストール（CSR を作った Mac の秘密鍵と対になる）。

> 注: Developer ID 証明書は Team あたりの作成数に上限がある。既存があれば再ダウンロードして使う。

---

## 2. keychain に入ったか確認

```bash
security find-identity -v -p codesigning
```

出力に次の形が現れれば OK。`( )` 内の英数字が **Team ID**：

```
1) ABCD1234... "Developer ID Application: Your Name (TEAMID)"
```

この **`Developer ID Application: Your Name (TEAMID)`** 文字列をそのまま
`signing_identity`（または環境変数 `PYAPPDIST_SIGNING_IDENTITY`）に使う。

Team ID 単体は次でも確認できる（App Store Connect / メンバーシップページにも記載）：

```bash
# 上の find-identity の (...) 部分、または:
xcrun altool --list-providers ...   # （App Store Connect API 鍵がある場合）
```

---

## 3. 公証クレデンシャル（notarytool プロファイル）の作成

Apple ID パスワードや API 鍵を直接ビルドに渡さず、**keychain プロファイル**に保存しておく。
pyappdist はこのプロファイル名だけを使う。方式は2つ。

### 方式A: App 固有パスワード（手軽）

1. <https://appleid.apple.com> → サインインとセキュリティ → **App用パスワード** を生成
   （例 `abcd-efgh-ijkl-mnop`）。
2. プロファイルを作成：

```bash
xcrun notarytool store-credentials my-notary-profile \
  --apple-id you@example.com \
  --team-id TEAMID \
  --password abcd-efgh-ijkl-mnop
```

### 方式B: App Store Connect API キー（CI 向き・推奨度高）

1. App Store Connect → Users and Access → **Integrations / Keys** で API キーを発行
   （Issuer ID、Key ID、`AuthKey_XXXXXXXX.p8` をダウンロード。p8 は再DL不可なので保管）。
2. プロファイルを作成：

```bash
xcrun notarytool store-credentials my-notary-profile \
  --key /secure/AuthKey_XXXXXXXX.p8 \
  --key-id KEYID \
  --issuer ISSUER-UUID
```

どちらの方式でも、以降は `notary_profile = "my-notary-profile"`（または環境変数
`PYAPPDIST_NOTARY_PROFILE`）でこのプロファイルを参照する。

確認（資格情報が有効か）：

```bash
xcrun notarytool history --keychain-profile my-notary-profile
```

---

## 4. pyappdist への設定

`pyproject.toml` のターゲットに記述するか、環境変数で渡す（環境変数が config より優先されるのは
identity/profile のみ。詳細は `docs/signing.rst`）。

```toml
[[tool.pyappdist.targets]]
platform = "macos-arm64"
format = "dmg"
signing_identity = "Developer ID Application: Your Name (TEAMID)"
notary_profile   = "my-notary-profile"
# team_id     = "TEAMID"                    # 任意
# entitlements = "build/app.entitlements"   # 任意（未指定なら同梱python向けデフォルト）
```

環境変数で渡す場合：

```bash
export PYAPPDIST_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export PYAPPDIST_NOTARY_PROFILE="my-notary-profile"
```

---

## 5. 次にやること

ビルドと検証（`spctl` が **accepted** になることの確認まで）は `docs/signing.rst` の
**"Verifying a signed + notarized build"** に手順がある。要点だけ：

```bash
cd e2e/smoke
uv run pyappdist build macos-arm64       # codesign(Developer ID) → notarize → staple
xcrun stapler validate appdist/macos-arm64/dist/smoke-0.1.0.dmg
spctl -a -t open --context context:primary-signature -vvv appdist/macos-arm64/dist/smoke-0.1.0.dmg
```

公証が `Invalid` の場合は提出ログで原因（弾かれたバイナリ／entitlement）を確認：

```bash
xcrun notarytool log <submission-id> --keychain-profile my-notary-profile
```

---

## チェックリスト

- [ ] Apple Developer Program 登録済み
- [ ] Xcode CLT 導入済み（`notarytool`/`stapler`/`codesign`）
- [ ] **Developer ID Application** 証明書を login keychain に作成
- [ ] `security find-identity -v -p codesigning` で identity 文字列と Team ID を確認
- [ ] `notarytool store-credentials` で keychain プロファイル作成
- [ ] `notarytool history` でプロファイルが有効
- [ ] `signing_identity` / `notary_profile`（or 環境変数）を設定
- [ ] `uv run pyappdist build macos-arm64` → `spctl` が **accepted**

## 参考

- Apple: "Notarizing macOS software before distribution" / "Customizing the notarization workflow"
  （`notarytool`/`stapler`）
- Apple: "Creating Developer ID-signed software" / `man codesign`
- Hardened Runtime entitlements 一覧（`com.apple.security.cs.*`）
