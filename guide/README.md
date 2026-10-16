# Autolingua Desktop ユーザーガイド

React + TypeScript + CSS で作成したオンライン専用の静的サイトです。
初期設定の本文は提供された原稿を収録しています。第2章「最初の翻訳」から第9章「自動化・外部連携」までは `.ui` と Python の実装を確認して作成しています。
モデル名を含む原稿の記述について、最新情報や全項目の実装との照合は別途必要です。

## 起動・検証

Node.js 24 以上を使用します。このディレクトリで実行してください。

```powershell
npm install
npm run dev
npm test
npm run build
```

この作業環境では兄弟プロジェクト `../../auto_lingua/node_modules` にあるReact・Vite等を
再利用できます。Font Awesomeを含む必要な依存は `npm install` で導入してください。
依存は `guide/node_modules` を優先し、兄弟プロジェクトのファイルは変更しません。

`npm run build` は翻訳検証、TypeScriptチェック、Viteビルドを順に実行します。
出力は `dist/` です。`npm run preview` でビルド成果物を確認できます。

## ファイル構成

- `src/components.tsx`: 内部リンク、注意枠、本文セクション、説明リスト、ページ内目次、前後ページリンク。
- `src/Icon.tsx`: Font Awesome Freeの使用アイコンをまとめた共通SVGコンポーネント。
- `src/BrandLogo.tsx`: 画像生成したロゴのWebPを表示する共通部品。
- `public/brand/`: ロゴとペンギンアイコンのWebP。SVGロゴはサイトでは使用しません。
- `src/content.ts`: ページの順序、見出しID、表示する部品と翻訳キー。文章は置きません。
- `src/script-reference.ts`: 第9章から参照する、独立したスクリプト言語リファレンスのページ定義。
- `src/ScriptCode.tsx`・`src/scriptTokens.ts`: スクリプト例の色分け表示。型・予約語・関数・文字列・数値・コメント・記号を区別し、文字列として安全に描画します。
- `src/i18n.ts`: 翻訳キーの型、言語一覧、文章JSONの取得と形式チェック。
- `src/App.tsx`: 共通レイアウト、URLによるページ切り替え、言語切り替え。
- `src/style.css`: 共通スタイルとスマートフォン・印刷向けレイアウト。
- `public/locales/ja.json`: 基準言語の文章。HTML・URL・画面設定は含めません。
- `scripts/validate-locales.mjs`: 重複キー、空の文章、文字列以外の値、言語間のキーの過不足を検証。

## 本文の追加

1. `ja.json` に一意なキーと文章を追加します。例: `settings.general.description`。
2. `content.ts` の該当ページにセクションを追加し、そのキーを参照します。
3. セクション内には `paragraph`、`notice`、`code`、`definitions`、`links`、`guideLinks`、`table` を配置できます。`code` は改行を保持してスクリプトを色分け表示し、`guideLinks` は現在の言語でガイド内の別ページへ移動します。
4. `npm run build` で確認します。存在しないキーの参照はTypeScriptエラーになります。

目次・見出し・前後ページリンクは同じページ定義を参照します。
独立した仕様ページは `referencePages` に登録し、`parentSlug` で親章を指定します。全9章の番号を維持したまま、親章の下にリンクを表示します。
同じ用途の見出しを複数のJSONキーに重複登録する必要はありません。
本文は文字列として描画し、HTMLを解釈しません。

アイコンはFont Awesome FreeのSolidを使用し、必要なアイコンだけをビルドに含めます。
CDNやアイコンフォントの追加読み込みは不要です。
Font Awesomeの帰属表示とライセンス情報は `public/third-party-notices.txt` に収録し、公開成果物にも含めます。

## テーマ

ヘッダーの月・太陽ボタンでライト／ダークを切り替えます。
初回はOSの配色設定に追従し、選択後は `localStorage` に保存して次回も使用します。
ストレージが利用できない場合も、そのページ内では切り替えられます。
`public/theme.js` を描画前に実行し、再読み込み時のテーマのちらつきを抑えます。
配色は `src/style.css` の共通CSS変数で管理します。

## 言語の追加

1. `public/locales/ja.json` をもとに `en.json` などを作成し、値だけ翻訳します。
2. `language.name` にコンボボックスで表示する言語の自称（例: `English`）を指定します。全言語で同じキーを使います。キー重複禁止は同じJSONファイル内に適用されます。
3. `npm run build` を実行します。`public/locales/*.json` からファイル名を言語コード、`language.name` を表示名として自動登録するため、TypeScriptの変更は不要です。開発サーバーの起動中に言語を追加した場合は再起動してください。

検証はパース前の元テキストから重複キーを検出し、ファイル名・行番号・キーを表示します。
エスケープ表記による同名キーも検出します。基準言語の変更時はすべての翻訳を揃えてください。
言語切り替えは現在のページと見出しのURLを維持します。

## 公開

サイトのルートに `dist/` の内容を配置します。
`/ja/guide/setup` のようなURLの直接アクセスに対応するため、ホスティング側で
実在しないページパスを `index.html` にフォールバックする設定が必要です。
`/assets/` と `/locales/` は静的ファイルを優先して配信してください。

ルート以外のサブディレクトリへの公開には、Viteの `base` とアプリ内のURL組み立ての変更が必要です。
`file://` での閲覧は対象外です。ブラウザから `/locales/{言語}.json` を取得します。
