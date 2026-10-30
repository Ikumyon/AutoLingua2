# AUTOlingua Desktop

Paradoxゲーム等のローカライズファイルに向けた、AI翻訳・差分追従・用語集管理を行うマルチプラットフォーム・デスクトップアプリです。

> [!NOTE]
> **アプリの利用者（エンドユーザー）向け情報**
> - アプリのダウンロード: [GitHub Releases](https://github.com/Ikumyon/AutoLingua2/releases)
> - 詳しい使い方・操作マニュアル: **[公式ユーザーガイド (Web)](https://ikumyon.github.io/AutoLingua2/)**

本ドキュメントは、AUTOlingua のソースコードを変更・拡張・ビルドしたい開発者・コントリビューター向けの開発ガイドです。

---

## 🛠 アーキテクチャ & 技術スタック

AUTOlingua は Python の GUI アプリケーションを中核としつつ、パフォーマンスと安定性が求められる部分に Rust や Web フロントエンド技術を組み合わせて構成されています。

| レイヤー / 領域 | 主要技術 | 役割・内容 |
|---|---|---|
| **GUI & コア** | Python 3.14+ / PySide6 (Qt) | メインUI制御、翻訳パイプライン、設定、プラグイン機構 |
| **画面定義** | Qt Designer (`ui/*.ui`) | 画面ウィジェット・レイアウトの静的定義 |
| **ネイティブ基盤** | Rust (Cargo) | 高速ランチャー、ファイル監視デーモン、ネイティブ拡張、アップデーター |
| **Web UI** | React / TypeScript / Vite | アプリ内AIチャット画面 (`web/`) |
| **ドキュメント** | React / TypeScript / VitePress 等 | GitHub Pages 公開用ユーザーガイド (`guide/`) |
| **パッケージング** | PyInstaller / GitHub Actions | Windows / Linux 向けポータブルパッケージの自動生成 |

---

## 🚀 開発環境のセットアップ

### 前提条件
- **Python**: 3.14 以上
- **Rust / Cargo**: 最新の stable ツールチェーン
- **Node.js**: v18 以上 (web/ 開発時)
- **C++ コンパイラ**: Windows の場合は MSVC (Visual Studio Build Tools 等)

### 1. リポジトリのクローンと Python 環境構築
```powershell
git clone https://github.com/Ikumyon/AutoLingua2.git
cd auto_lingua2

# 仮想環境の作成と有効化
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 依存関係のインストール（editable モード）
pip install -e .
```

### 2. ネイティブコンポーネント & Web UI のビルド
アプリの完全な起動には、Rust クレートおよび Web チャット UI の事前ビルドが必要です。

```powershell
# 1. Rust クレート（ランチャー・ファイル監視・アップデーター等）のビルド
cargo build --release

# 2. AIチャット Web UI のビルド
cd web
npm install
npm run build
cd ..

# 3. UI翻訳バイナリ (.qm) のコンパイル
python .github/ui_translations.py --compile
```

---

## 💻 ローカル実行 & デバッグ

```powershell
# Python から直接起動（開発・デバッグ用）
python -m autolingua2

# またはビルド済みランチャー経由で起動
.\target\release\autolingua-launcher.exe
```

---

## 📂 プロジェクト構成

```text
auto_lingua2/
├── crates/             # Rust クレート群
│   ├── autolingua-launcher/       # アプリケーション起動ランチャー
│   ├── autolingua-source-watcher/ # ファイル変更監視バックグラウンドデーモン
│   ├── autolingua-updater/        # 自動更新・パッチ適用ツール
│   └── autolingua-native/         # 高速テキスト差分抽出等のネイティブ拡張
├── src/autolingua2/    # Python アプリケーション本体
│   ├── ai/                        # AIプロバイダー連携 (OpenAI, Gemini, Claude, Ollama等)
│   ├── gui/                       # ウィンドウ・ダイアログ・イベントハンドラ
│   ├── plugins/                   # 拡張プラグイン機構
│   ├── translation/               # 翻訳パイプライン、差分抽出、用語集適用
│   ├── export/                    # 各種形式（YAML, ParaTranz, BMFont等）のエクスポート
│   └── app.py                     # エントリーポイント
├── ui/                 # Qt Designer で編集可能な画面定義ファイル (.ui)
├── translations/       # 多言語UI翻訳ソース (.ts) とメタデータ
├── web/                # AIチャット用 Web フロントエンド (React / TypeScript)
├── guide/              # ドキュメントサイト (ユーザーガイド)
└── .github/workflows/  # CI/CD ビルド・リリースワークフロー
```

各サブプロジェクトの詳細は、各フォルダ内の README を参照してください。
- [Rust クレートの構成とビルド](crates/README.md)
- [AIチャット表示のビルド](web/README.md)
- [ユーザーガイドの起動・ビルド・公開](guide/README.md)

---

## 🔧 ソースコードの改造・拡張ガイド

### 1. 画面UIの変更 (`ui/`)
- ウィジェット配置や静的レイアウトはすべて `ui/*.ui` に定義されています。
- Qt Designer（または `pyside6-designer`）を使って GUI で直感的に編集できます。
- **実装原則**: 静的なレイアウトは `.ui` に記述し、ボタン押下時のロジックや動的表示制御は Python 側（`src/autolingua2/gui/`）で実装します。

### 2. AIプロバイダー・翻訳ロジックの追加 (`src/autolingua2/ai/`)
- 新しい LLM API やローカルモデル連携を追加する場合は、`src/autolingua2/ai/` 配下のプロバイダーインターフェースを実装します。

### 3. プラグインの追加 (`src/autolingua2/plugins/`)
- 独自のテキスト前処理・後処理やファイル変換ロジックをプラグインとして組み込むことができます。

### 4. 多言語UI翻訳の編集 (`translations/`)
- 各言語向けに Qt Linguist 形式の `.ts` ファイルが用意されています。
- 翻訳の更新や追加を行った後、以下のスクリプトで `.qm` バイナリへ一括コンパイルします：
  ```powershell
  python .github/ui_translations.py --compile
  ```

---

## 📦 パッケージング & 配布用ビルド

### ローカルでの PyInstaller ビルド
Windows 向けのスタンドアロン配布パッケージをローカルで作成する場合：
```powershell
python -m PyInstaller --noconfirm AUTOlingua2.spec
```

### Linuxのローカル配布ビルド
Linux配布ビルドはUbuntu 24.04（x86_64）を基準に、`AUTOlingua2.spec` から
[共通Fcitx処理](.github/linux_fcitx.py)を実行します。ローカルでも同じspecを使います。
既存のPython・Rust・Web・UI生成の準備に加え、以下のビルド依存が必要です。

```bash
sudo apt-get install build-essential git cmake ninja-build extra-cmake-modules libx11-dev libxcb1-dev libxkbcommon-dev libwayland-dev libegl1-mesa-dev libgl1-mesa-dev patchelf binutils
python -m pip install aqtinstall==3.3.0
python -m PyInstaller --noconfirm AUTOlingua2.spec
```

実際のPySide6の `qVersion()` と同じQt SDKを `build/linux-fcitx/sdk` に取得し、
fcitx5-qt **5.1.16 / commit `115750044f3d0db16ca5859808c7da830fd1ff52`** をビルドします。
既存SDKを使う場合は `AUTOLINGUA_QT_SDK=/path/to/Qt/6.x.y/gcc_64` を指定できます。
SDKには `qmake` などの実行に必要なICUも含めてください。自動取得ではICUアーカイブも取得します。
異なるQt版へのフォールバックは行いません。Qtのprivate APIを使用するため同じ版が必要です。
SDKは配布せず、生成プラグイン・実行時依存（OS側のglibcを除く）・ライセンスと
Fcitxの対応ソースを同梱します。版・欠落・依存解決・SDK絶対パスを静的検査し、不整合はビルド失敗にします。
開発起動ではこの処理を実行せず、入力方式の環境変数やOS側のFcitx・IBus・Wayland設定も変更しません。

調査時点の公開 `v0.9.0beta` の `AUTOlingua2-linux.tar.gz` を直接確認したところ、
`platforminputcontexts` にはIBus・Compose・Virtual Keyboardがあり、Fcitxはありませんでした。
アーカイブのSHA-256は `0fdb23654607c84b02813266b0152dba386b1b5ee31fd513f70a5ec92e08edca` です。
この欠落は確認済みですが、個々のOS環境での日本語入力の成否は別途実機確認が必要です。
参考: [Qtのプラグイン配布](https://doc.qt.io/qt-6/deployment-plugins.html)、
[FcitxとWayland](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland)、
[Flathubでのバージョン・タグオブジェクト固定例](https://github.com/flathub/org.fcitx.Fcitx5/blob/master/org.fcitx.Fcitx5.yaml)。

### GitHub Actions による自動リリース
本プロジェクトでは、バージョン管理を **Git タグ** で一元化しています。
`vMAJOR.MINOR.PATCH` 形式のタグを push すると、CI/CD ワークフロー（`Build desktop`）が自動実行され、Windows / Linux 向けの配布成果物が生成されます。

```powershell
# 例: v1.0.0 をリリースする場合
git tag v1.0.0
git push origin v1.0.0
```

- CI がタグから `VERSION`（例: `1.0.0`）を自動生成し、Python、Rust、実行ファイルメタデータに注入します。
- 手動でコード内のバージョン番号を書き換える必要はありません。

---

## 📄 ライセンス

[MIT License](LICENSE) — Copyright (c) 2026 Ikumyon

同梱する外部ライブラリ・素材には、それぞれのライセンスが適用されます。
ユーザーガイドで使用するアイコンのライセンス情報は [third-party-notices.txt](guide/public/third-party-notices.txt) をご参照ください。
