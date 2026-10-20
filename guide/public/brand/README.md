# ブランド画像

- `autolingua-desktop.svg`: ヘッダーに使用する新しいロゴ。
  `assets/images/autolingua_desktop_logo.svg` から収録し、ガイド内の `/brand/autolingua-desktop.svg` を参照します。
- `autolingua-desktop.webp`: 以前使用していた画像生成ロゴ。現在のヘッダーでは使用していません。
- `app.webp`: `assets/images/app.png` を320px幅に縮小してWebPへ変換したもの。

ロゴは背景と枠を付けず、ヘッダー上へ直接表示します。
ライトテーマでは元のネイビーとシアン、ダークテーマでは `#dark` フラグメントでネイビー部分を明るい文字色へ切り替えます。
シアンのアクセントは維持し、文字の縁取りも暗い背景に合わせます。元の `assets/images/` のSVGは変更しません。
いずれもサイトと一緒に配信し、外部画像サービスへの依存はありません。
