# Autolingua Desktop

Paradoxゲームのローカライズファイルを中心に、AI翻訳・編集・確認・出力を行うデスクトップアプリです。

**[ユーザーガイドを読む](https://ikumyon.github.io/AutoLingua2/)**

## 主な機能

- **AI翻訳**：ChatGPTへのサインイン、OpenAI・Google Gemini・Anthropic Claudeへの接続とモデル設定。
- **翻訳の編集・確認**：原文と訳文の一覧表示、検索・絞り込み、モデルごとの翻訳比較。
- **プロジェクト管理**：原文の更新差分の確認、フォルダ監視、サムネイルの加工と出力。
- **用語集・口調**：用語集の作成・継承・取り込み・書き出し、通常口調と条件付き口調の設定。
- **ファイル出力**：Paradox YAML、ParaTranz JSON、BMFont用の使用文字一覧の出力。
- **AIチャット**：資料や翻訳内容を参照した相談と、提案された変更の適用。
- **自動化・外部連携**：スクリプト、トリガーによる自動実行、MCP接続。

## 使い方

初回起動時のウィザードで表示言語とAIの接続を設定し、プロジェクトを作成して原文を取り込みます。
翻訳・確認後、用途に合った形式でファイルを出力します。

- [初期設定](https://ikumyon.github.io/AutoLingua2/ja/guide/setup)
- [最初の翻訳](https://ikumyon.github.io/AutoLingua2/ja/guide/first-translation)
- [困ったとき・アプリの更新](https://ikumyon.github.io/AutoLingua2/ja/guide/support)

ガイドは日本語を含む16言語に対応しています。ページ右上から表示言語を切り替えられます。

## 開発

アプリ本体はPython・PySide6、ランチャーやネイティブ処理はRust、AIチャットの表示とオンラインガイドはReact・TypeScriptで構成しています。

| ディレクトリ | 内容 |
| --- | --- |
| `src/autolingua2/` | アプリ本体、翻訳処理、プラグイン、各種サービス |
| `ui/` | Qt Designerの画面定義 |
| `crates/` | Rust製ランチャー、ネイティブライブラリ、監視デーモン、アップデーター |
| `web/` | アプリ内AIチャットのWeb表示 |
| `guide/` | GitHub Pagesで公開するユーザーガイド |
| `assets/`・`theme/` | 画像、翻訳リソース、テーマ、アイコン |

Pythonの対応範囲と依存関係は [pyproject.toml](pyproject.toml) に記載しています。
各部分のビルド手順は、それぞれのREADMEを参照してください。

- [Rustの構成とビルド](crates/README.md)
- [AIチャット表示のビルド](web/README.md)
- [ユーザーガイドの起動・ビルド・公開](guide/README.md)

ユーザーガイドは、`main` の `guide/` または公開ワークフローを更新すると、GitHub ActionsがビルドしてGitHub Pagesへ公開します。
アプリ本体だけの変更ではガイドを再ビルドしません。

### ビルドの検証

GitHub Actionsの **Build desktop** でWindows・Linuxのビルドを検証します。
`main` へのpush、プルリクエスト、手動実行に対応し、ガイドやMarkdownだけの変更は対象外です。

両OSでチャット画面の型チェックとビルド、Rustの4コンポーネントのビルド、
Pythonネイティブ拡張の読み込み、Qtリソースの変換、PyInstallerによるパッケージ作成を行います。
成功した配布物は各実行のArtifactsから7日間ダウンロードできます。
Linux版は実行権限を維持するためtar.gzにまとめます。
GUIの起動・操作テストとリリース公開は行いません。

## ライセンス

[MIT License](LICENSE) — Copyright (c) 2026 Ikumyon

同梱する外部ライブラリ・素材には、それぞれのライセンスが適用されます。
ガイドで使用するアイコンのライセンス情報は [third-party-notices.txt](guide/public/third-party-notices.txt) に記載しています。
