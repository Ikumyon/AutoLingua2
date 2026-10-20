# Autolingua Desktop ユーザーガイド

React + TypeScript + CSS で作成したオンライン専用の静的サイトです。
初期設定の本文は提供された原稿を収録しています。基本操作から自動化まで、`.ui` と Python の実装を確認して記述しています。
全10章と14の子ページで構成し、親ページには概要と基本操作、子ページには詳細な手順・設定の意味・使用例・結果確認を掲載しています。
モデル名など外部サービス側の情報は、利用時点の接続先でも確認してください。

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
- `src/BrandLogo.tsx`: ガイド内の `/brand/autolingua-desktop.svg` を表示する共通部品。
- `public/brand/`: 現在のSVGロゴ、ペンギンアイコンのWebPと旧ロゴ。ガイド単体で配信できるよう画像を収録します。
- `src/content.ts`: ページの順序、見出しID、表示する部品と翻訳キー。文章は置きません。
- `src/hierarchy.ts`: 章の順序、子ページへの説明の配置、増補分のページ構成と旧アンカーの移動先。文章は置きません。
- `src/imageLabels.ts`・`src/firstTranslationImageLabels.ts`・`src/captureImageLabels.ts`: スクリーンショットに重ねる字幕の翻訳キー、元画像の寸法、配置座標。日本語以外の表示では選択言語の字幕を重ね、WebP自体は変更しません。
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
子ページは `hierarchy.ts` で構成し、`referencePages` と `parentSlug` で親章に紐付けます。子ページに章番号は付けず、サイドバーと親ページ末尾から移動できます。
前後ページリンクは親章・その子ページ・次の章の順です。移動した既存の節は、旧URLのアンカーから新しい子ページへ転送します。
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
エスケープ表記による同名キーも検出します。既存キーは引き続き全言語で必須です。
本文・見出し・画像キャプション・画像内字幕は、すべての言語JSONで同じキーを揃えます。増補分は `details.`、追加キャプチャの字幕は `details.shots.` で始まるキーにまとめています。日本語による未翻訳の補完は行いません。
翻訳は同じキーを各言語JSONへ追加すれば反映されます。不明なキー・空文字・キーの欠落はビルド時と読み込み時にエラーにします。
言語切り替えは現在のページと見出しのURLを維持します。

## 現在の階層

1. 初期設定
2. 最初の翻訳
3. プロジェクトの管理：原文の更新とフォルダ監視／サムネイルの加工と出力
4. 翻訳・編集・確認
5. 用語集・口調：作成・編集・継承／取り込み・書き出し／通常口調と条件付き口調
6. 翻訳ファイルの出力：Paradox YAML／ParaTranz JSON／BMFont用の使用文字一覧
7. AIチャット
8. アプリの設定：AIの接続とモデル設定
9. 自動化・外部連携：スクリプトの作成と実行／トリガー／言語リファレンス／本体へのMCP接続／外部資料へのMCP接続
10. 困ったとき・アプリの更新

## 公開

GitHub Pages の公開先は `https://ikumyon.github.io/AutoLingua2/` です。
リポジトリの Settings → Pages → Source を **GitHub Actions** に設定します。
`main` へのpushで `guide/` または `.github/workflows/guide-pages.yml` が更新されると、
依存の導入、翻訳検証、型チェック、ビルド、公開を順に実行します。
Actions の **Publish guide → Run workflow** から手動でも実行できます。
アプリ本体だけの変更では実行しません。`dist/` はGitに含めません。

公開パスはPagesの設定から取得し、画像・翻訳・内部リンクにも適用します。
ローカルで公開用のビルドを確認する場合は、次のように指定します。

```powershell
$env:GUIDE_BASE_PATH = '/AutoLingua2/'
npm run build
npm run preview
```

GitHub Pagesで各ページを直接開けるよう、ビルド時に `404.html` にも
アプリのエントリーを出力します。直接アクセス時のHTTPステータスは404ですが、
URLを維持して該当ページを表示します。他のホスティングでは `index.html` への
フォールバックを設定すると通常の200で配信できます。
`file://` での閲覧は対象外です。
