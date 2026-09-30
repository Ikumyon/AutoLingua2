# Rust構成

リポジトリ直下の `Cargo.toml` と `Cargo.lock` で、2つのクレートを管理します。
Cargoの成果物はリポジトリ直下の `target/` に出力します。

## クレート

- `launcher`: Slintの起動画面と本体プロセスの起動。`src/launch/` に起動対象の解決、監視、時間判定を配置します。UI更新は `src/ui.rs`、ログは `src/logging.rs` に置きます。
- `autolingua2-native`: ランチャーとPython本体が利用するライブラリ。`src/bootstrap/` に起動通信、`src/encoding.rs` に文字コード処理、`src/platform/` にOS固有処理を配置します。

`bootstrap/` は `context`、`protocol`、`progress`、`connection`、`core`、`bindings` に分かれます。公開型と関数は `mod.rs` から再公開し、利用側の公開パスを維持します。

`platform/windows/` と `platform/linux/` は同じ分類を使います。

| ファイル | 配置する処理 |
| --- | --- |
| `mod.rs` | モジュール宣言と公開窓口 |
| `desktop.rs` | デスクトップ連携、コンソール、フォルダ表示 |
| `paths.rs` | 開発用Python、ログ、ランタイムの保存先 |
| `process.rs` | 実行ファイル判定、起動設定、プロセスグループ、生存監視 |
| `ipc.rs` | OS固有の接続、ストリーム、リスナー |
| `security.rs` | ユーザー識別、権限、乱数、ロックファイル作成 |

## ビルドと検証

Python拡張のfeatureがランチャーに統合されないよう、パッケージ別にビルドします。
引数なしのCargoコマンドは `default-members` によりランチャーを対象とします。

```powershell
cargo build --locked --release -p autolingua2-native
cargo build --locked --release -p autolingua-launcher
cargo test --locked -p autolingua2-native --no-default-features
cargo check --locked -p autolingua2-native --all-targets
cargo test --locked -p autolingua-launcher
```

Windowsの配置作業を含むビルドは既存の `scripts/build_rust.bat` を使用します。
Python拡張は引き続き `build/native/`、配布物は `dist/AUTOlingua2/` に配置します。
Linux固有処理の動作検証はLinux環境で実施します。
