#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod apply;
mod check;
mod download;
mod extract;
mod logging;
mod platform;
mod ui;

use std::path::PathBuf;

fn resolve_default_project_root() -> PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if parent
                .file_name()
                .and_then(|s| s.to_str())
                .map(|s| s.eq_ignore_ascii_case("core"))
                .unwrap_or(false)
            {
                if let Some(root) = parent.parent() {
                    return root.to_path_buf();
                }
            }
            return parent.to_path_buf();
        }
    }
    PathBuf::from(".")
}

fn print_help() {
    println!(
        "AUTOlingua2 Updater\n\
        Usage:\n\
          autolingua-updater check [options]       更新確認を行い結果をJSON出力\n\
          autolingua-updater gui [options]         更新UI画面を表示してDL・適用\n\n\
        Check Options:\n\
          --project-root <PATH>     プロジェクトルートパス\n\
          --current-version <VER>   現在のバージョン\n\
          --url <URL>               カスタム更新メタデータURL\n\
          --json                    JSON形式で結果を出力 (規定値)\n\n\
        GUI Options:\n\
          --project-root <PATH>     プロジェクトルートパス\n\
          --download-url <URL>      ダウンロードURL\n\
          --current-version <VER>   現在のバージョン\n\
          --new-version <VER>       新バージョン\n\
          --sha256 <HASH>           期待されるSHA-256ハッシュ\n\
          --parent-pid <PID>        終了待機する親プロセスのPID\n\
          --auto-apply              準備完了後に確認を挟まず即時適用\n\
          --internal-apply          一時コピーから起動された適用モード\n"
    );
}

fn main() {
    let mut args = std::env::args().skip(1);
    let subcmd = args.next();

    match subcmd.as_deref() {
        Some("check") | Some("--check") => {
            let mut project_root = None;
            let mut current_version = env!("CARGO_PKG_VERSION").to_string();
            let mut custom_url = None;

            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--project-root" => {
                        if let Some(val) = args.next() {
                            project_root = Some(PathBuf::from(val));
                        }
                    }
                    "--current-version" => {
                        if let Some(val) = args.next() {
                            current_version = val;
                        }
                    }
                    "--url" => {
                        if let Some(val) = args.next() {
                            custom_url = Some(val);
                        }
                    }
                    "--json" => {} // 常にJSON出力
                    _ => {}
                }
            }

            let root = project_root.unwrap_or_else(resolve_default_project_root);
            match check::check_update(&root, &current_version, custom_url.as_deref()) {
                Ok(info) => {
                    let json = serde_json::to_string_pretty(&info).unwrap_or_else(|_| "{}".to_string());
                    println!("{json}");
                    std::process::exit(0);
                }
                Err(err) => {
                    eprintln!("Error: {err}");
                    let err_json = serde_json::json!({
                        "has_update": false,
                        "error": err
                    });
                    println!("{}", err_json);
                    std::process::exit(1);
                }
            }
        }
        Some("gui") | Some("--gui") => {
            let mut project_root = None;
            let mut download_url = String::new();
            let mut current_version = env!("CARGO_PKG_VERSION").to_string();
            let mut new_version = "—".to_string();
            let mut sha256 = None;
            let mut parent_pid = 0u32;
            let mut auto_apply = true; // UpdateDialog.ui で決定済みのため自動適用
            let mut is_internal_apply = false;

            let all_raw_args: Vec<String> = std::env::args().skip(2).collect();

            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--project-root" => {
                        if let Some(val) = args.next() {
                            project_root = Some(PathBuf::from(val));
                        }
                    }
                    "--download-url" => {
                        if let Some(val) = args.next() {
                            download_url = val;
                        }
                    }
                    "--current-version" => {
                        if let Some(val) = args.next() {
                            current_version = val;
                        }
                    }
                    "--new-version" => {
                        if let Some(val) = args.next() {
                            new_version = val;
                        }
                    }
                    "--sha256" => {
                        if let Some(val) = args.next() {
                            sha256 = Some(val);
                        }
                    }
                    "--parent-pid" => {
                        if let Some(val) = args.next() {
                            parent_pid = val.parse().unwrap_or(0);
                        }
                    }
                    "--auto-apply" => {
                        auto_apply = true;
                    }
                    "--internal-apply" => {
                        is_internal_apply = true;
                    }
                    _ => {}
                }
            }

            let root = project_root.unwrap_or_else(resolve_default_project_root);

            // 自身が正規の配置先にある場合、GUI表示前の起動直後に一時コピーへ引き継ぐ
            if !is_internal_apply {
                if let Ok(current_exe) = std::env::current_exe() {
                    if !apply::is_running_from_temp(&current_exe, &root) {
                        let mut forwarded = vec!["gui".to_string()];
                        forwarded.extend(all_raw_args);
                        if let Err(e) = apply::handoff_to_temp_updater(&root, &forwarded) {
                            eprintln!("一時アップデーターの起動に失敗しました: {e}");
                        }
                    }
                }
            }

            // download_url が未指定の場合、アップデーター自ら check を行い解決する
            if download_url.is_empty() {
                if let Ok(info) = check::check_update(&root, &current_version, None) {
                    if let Some(url) = info.download_url {
                        download_url = url;
                        new_version = info.latest_version;
                        sha256 = info.sha256;
                    }
                }
            }

            let params = ui::GuiParams {
                project_root: root,
                download_url,
                current_version,
                new_version,
                sha256,
                parent_pid,
                auto_apply,
                is_internal_apply,
            };

            if let Err(err) = ui::run_gui(params) {
                eprintln!("UI Error: {err}");
                std::process::exit(1);
            }
        }
        _ => {
            print_help();
        }
    }
}
