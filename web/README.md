# AIチャットのWeb表示

React＋TypeScriptでMarkdown、構造化Generative UI、生成HTMLを描画します。
Qt側が入力、文中参照、AI通信、変更適用・ジョブ操作を担当します。

## ビルド

兄弟プロジェクト `../auto_lingua/node_modules` のReact、React DOM、TypeScript、Viteと型定義を再利用します。
このディレクトリから見た実パスは `../../auto_lingua/node_modules` です。
兄弟プロジェクトのファイルは変更しません。

React／React DOMは既存の導入先をローカル依存として指定しています。
必要な実行依存が省略されないよう、peer依存も含めて導入します。

```powershell
cd web
npm install --include=peer --no-package-lock --ignore-scripts --no-audit --no-fund
npm run typecheck
npm run build
```

`assets/chat` に出力した資産をQtが読み込み、PyInstallerの配布にも同梱します。
アプリ実行時にはNode.jsサーバーやCDNを使いません。
Pythonアプリ・配布のビルド前にWeb表示をビルドしてください。

## チャンクサイズの警告

依存ライブラリはパッケージ単位で分割し、400 kBを目安にさらに分割します。
言語辞書とMermaidの図種別の既存の遅延読み込みは維持します。
500 kBの警告基準は変更しません。分割はモジュール単位なので、単一の大きな言語辞書や
WASMモジュールについては警告が残る場合があります。

## ユーザーによる確認項目

- 日本語Markdown、長いコード・表、分数・行列、Mermaidの表示と各コピー操作。
- `json-ui` の入力・選択・スライダーを操作し、ボタンから現在の値をAIへ送信できること。
- 存在しない部品、不正JSON、循環したUI仕様はエラーと原文確認になり、HTMLへ自動転換されないこと。
- 生成HTML内の操作、コード切り替え、拡大表示と操作状態の保持。
- ファイルと選択行の文中DnD、内容確認、削除・Undo／Redo、同名資料の区別。
- 選択・並べ替え・ファイル編集後も挿入時の内容が保たれること。
- IME確定、音声入力、送信失敗時の入力保持、会話の停止とジョブ中止。
- 変更の部分適用・取り消し、過去の会話を読んでいるときのスクロール保持、テーマ・表示言語の切り替え。
