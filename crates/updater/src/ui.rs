use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use slint::ComponentHandle;

use crate::apply;
use crate::download::{self, DownloadProgress};
use crate::extract;
use crate::logging::ProcessLogger;

slint::include_modules!();

#[derive(Debug, Clone)]
pub struct GuiParams {
    pub project_root: PathBuf,
    pub download_url: String,
    pub current_version: String,
    pub new_version: String,
    pub sha256: Option<String>,
    pub parent_pid: u32,
    pub auto_apply: bool,
    pub is_internal_apply: bool,
}

pub fn run_gui(params: GuiParams) -> Result<(), String> {
    let dialog = UpdateProgressDialog::new().map_err(|e| format!("UIの初期化に失敗しました: {e}"))?;
    let logger = ProcessLogger::new();

    let version_str = format!("{} → {}", params.current_version, params.new_version);
    dialog.set_download_version(version_str.clone().into());
    dialog.set_ready_version(version_str.clone().into());
    dialog.set_apply_version(version_str.into());

    let cancel_flag = Arc::new(AtomicBool::new(false));

    // コールバック接続
    let cancel_flag_clone = cancel_flag.clone();
    let dialog_weak = dialog.as_weak();
    dialog.on_cancel_download(move || {
        cancel_flag_clone.store(true, Ordering::Release);
        if let Some(d) = dialog_weak.upgrade() {
            d.window().hide().unwrap_or(());
        }
    });

    let dialog_weak = dialog.as_weak();
    dialog.on_later(move || {
        if let Some(d) = dialog_weak.upgrade() {
            d.window().hide().unwrap_or(());
        }
    });

    let dialog_weak = dialog.as_weak();
    dialog.on_close_requested(move || {
        if let Some(d) = dialog_weak.upgrade() {
            d.window().hide().unwrap_or(());
        }
    });

    // ログ更新ヘルパー
    let logger_clone = logger.clone();
    let dialog_weak = dialog.as_weak();
    let log_fn = Arc::new(move |msg: &str| {
        let all_logs = logger_clone.log(msg);
        let weak = dialog_weak.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(d) = weak.upgrade() {
                d.set_process_log(all_logs.into());
            }
        });
    });

    (log_fn)("アップデーターが起動しました");
    (log_fn)(&format!("対象プロジェクト: {}", params.project_root.display()));

    // 作業ディレクトリの準備
    let updates_dir = params.project_root.join(".data").join("updates");
    let downloaded_zip = updates_dir.join("downloaded").join("update.zip");
    let extracted_dir = updates_dir.join("extracted");

    // 「本体を終了して更新」クリック時（または即時適用時）の処理
    let params_clone = params.clone();
    let log_fn_clone = log_fn.clone();
    let dialog_weak = dialog.as_weak();
    let extracted_for_apply = extracted_dir.clone();
    let start_apply = Arc::new(move || {
        let params = params_clone.clone();
        let log = log_fn_clone.clone();
        let weak = dialog_weak.clone();
        let extracted_path = extracted_for_apply.clone();

        // Page 2 (適用中) へ切り替え
        let _ = slint::invoke_from_event_loop({
            let weak = weak.clone();
            move || {
                if let Some(d) = weak.upgrade() {
                    d.set_page(2);
                    d.set_apply_phase("更新適用を開始します…".into());
                    d.set_apply_percent(0);
                }
            }
        });

        // 実行中バイナリが正規の配置先にある場合、一時コピーに引き継ぐ
        let current_exe = match std::env::current_exe() {
            Ok(exe) => exe,
            Err(e) => {
                log(&format!("実行ファイルパス取得エラー: {e}"));
                return;
            }
        };

        if !params.is_internal_apply && !apply::is_running_from_temp(&current_exe, &params.project_root) {
            log("アップデーターの一時コピーへ処理を引き継ぎます…");
            let mut forwarded = vec![
                "gui".to_string(),
                "--project-root".to_string(),
                params.project_root.to_string_lossy().to_string(),
                "--download-url".to_string(),
                params.download_url.clone(),
                "--current-version".to_string(),
                params.current_version.clone(),
                "--new-version".to_string(),
                params.new_version.clone(),
                "--parent-pid".to_string(),
                params.parent_pid.to_string(),
            ];
            if let Some(sha) = &params.sha256 {
                forwarded.push("--sha256".to_string());
                forwarded.push(sha.clone());
            }

            if let Err(e) = apply::handoff_to_temp_updater(&params.project_root, &forwarded) {
                log(&format!("一時コピーへの引き継ぎに失敗しました: {e}"));
                let _ = slint::invoke_from_event_loop({
                    let weak = weak.clone();
                    move || {
                        if let Some(d) = weak.upgrade() {
                            d.set_page(3);
                            d.set_error_detail(e.into());
                        }
                    }
                });
            }
            return;
        }

        // 一時コピー側での適用実行スレッド
        thread::spawn(move || {
            let wait_pids = if params.parent_pid > 0 {
                vec![params.parent_pid]
            } else {
                vec![]
            };

            let log_for_apply = log.clone();
            match apply::execute_apply(
                &params.project_root,
                &extracted_path,
                &wait_pids,
                move |msg| log_for_apply(msg),
            ) {
                Ok(()) => {
                    log("更新が正常に完了しました。画面を閉じます。");
                    let _ = slint::invoke_from_event_loop({
                        let weak = weak.clone();
                        move || {
                            if let Some(d) = weak.upgrade() {
                                d.window().hide().unwrap_or(());
                            }
                        }
                    });
                    std::process::exit(0);
                }
                Err(e) => {
                    log(&format!("適用エラー: {e}"));
                    let _ = slint::invoke_from_event_loop({
                        let weak = weak.clone();
                        let err_msg = e.clone();
                        move || {
                            if let Some(d) = weak.upgrade() {
                                d.set_page(3);
                                d.set_error_detail(err_msg.into());
                            }
                        }
                    });
                }
            }
        });
    });

    let start_apply_clone = start_apply.clone();
    dialog.on_apply_update(move || {
        (start_apply_clone)();
    });

    // 準備状態の判定と開始処理
    let start_workflow = {
        let dialog_weak = dialog.as_weak();
        let log = log_fn.clone();
        let cancel_flag = cancel_flag.clone();
        let params = params.clone();
        let downloaded_zip = downloaded_zip.clone();
        let extracted_dir = extracted_dir.clone();
        let start_apply = start_apply.clone();

        move || {
            let weak = dialog_weak.clone();
            let log = log.clone();
            let cancel = cancel_flag.clone();
            let params = params.clone();
            let zip_path = downloaded_zip.clone();
            let ext_path = extracted_dir.clone();
            let apply_action = start_apply.clone();

            thread::spawn(move || {
                // 1. すでに解凍済みか、または有効なzipがあるかチェック
                let mut zip_ready = false;
                if zip_path.is_file() {
                    log("既存のダウンロード済み更新ファイルを検出しました。検証中…");
                    if let Some(expected_sha) = &params.sha256 {
                        match download::verify_sha256(&zip_path, expected_sha) {
                            Ok(true) => {
                                log("SHA-256 検証に成功しました");
                                zip_ready = true;
                            }
                            _ => {
                                log("既存ファイルのハッシュが一致しないため、再ダウンロードします");
                                let _ = std::fs::remove_file(&zip_path);
                            }
                        }
                    } else {
                        zip_ready = true;
                    }
                }

                // 2. zipが準備できていない場合はダウンロード
                if !zip_ready {
                    log("更新ファイルのダウンロードを開始します…");
                    let _ = slint::invoke_from_event_loop({
                        let weak = weak.clone();
                        move || {
                            if let Some(d) = weak.upgrade() {
                                d.set_page(0);
                                d.set_download_percent(0);
                                d.set_download_bytes("0 B / —".into());
                                d.set_download_speed_and_time("接続中…".into());
                            }
                        }
                    });

                    let weak_dl = weak.clone();
                    let log_dl = log.clone();
                    let res = download::download_file(
                        &params.download_url,
                        &zip_path,
                        &cancel,
                        move |progress: DownloadProgress| {
                            let weak = weak_dl.clone();
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(d) = weak.upgrade() {
                                    d.set_download_percent(progress.percent as i32);
                                    d.set_download_bytes(progress.format_bytes().into());
                                    d.set_download_speed_and_time(progress.format_speed_and_time().into());
                                }
                            });
                        },
                    );

                    if let Err(e) = res {
                        log_dl(&format!("ダウンロード失敗: {e}"));
                        let _ = slint::invoke_from_event_loop({
                            let weak = weak.clone();
                            move || {
                                if let Some(d) = weak.upgrade() {
                                    d.set_page(3);
                                    d.set_error_detail(e.into());
                                }
                            }
                        });
                        return;
                    }
                    log("ダウンロードが完了しました");

                    // ハッシュ検証
                    if let Some(expected_sha) = &params.sha256 {
                        log("SHA-256 チェックサムを検証しています…");
                        match download::verify_sha256(&zip_path, expected_sha) {
                            Ok(true) => log("SHA-256 検証OK"),
                            Ok(false) => {
                                let err = "SHA-256 ハッシュが一致しません。ファイルが破損している可能性があります。";
                                log(err);
                                let _ = slint::invoke_from_event_loop({
                                    let weak = weak.clone();
                                    move || {
                                        if let Some(d) = weak.upgrade() {
                                            d.set_page(3);
                                            d.set_error_detail(err.into());
                                        }
                                    }
                                });
                                return;
                            }
                            Err(e) => {
                                log(&format!("ハッシュ検証エラー: {e}"));
                                let _ = slint::invoke_from_event_loop({
                                    let weak = weak.clone();
                                    move || {
                                        if let Some(d) = weak.upgrade() {
                                            d.set_page(3);
                                            d.set_error_detail(e.into());
                                        }
                                    }
                                });
                                return;
                            }
                        }
                    }
                }

                // 3. 解凍・展開
                log("更新アーカイブの解凍・検証を開始します…");
                let weak_ext = weak.clone();
                let res = extract::extract_zip(
                    &zip_path,
                    &ext_path,
                    &cancel,
                    move |percent, current, total, name| {
                        let weak = weak_ext.clone();
                        let phase_str = format!("ファイルを展開しています ({current}/{total}): {name}");
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(d) = weak.upgrade() {
                                d.set_apply_percent(percent as i32);
                                d.set_apply_phase(phase_str.into());
                            }
                        });
                    },
                );

                if let Err(e) = res {
                    log(&format!("解凍エラー: {e}"));
                    let _ = slint::invoke_from_event_loop({
                        let weak = weak.clone();
                        move || {
                            if let Some(d) = weak.upgrade() {
                                d.set_page(3);
                                d.set_error_detail(e.into());
                            }
                        }
                    });
                    return;
                }
                log("更新アーカイブの解凍が完了しました");

                // 4. 準備完了または自動適用
                if params.auto_apply || params.is_internal_apply {
                    (apply_action)();
                } else {
                    log("更新の準備が完了しました。ユーザーの確認を待機します。");
                    let _ = slint::invoke_from_event_loop({
                        let weak = weak.clone();
                        move || {
                            if let Some(d) = weak.upgrade() {
                                d.set_page(1); // Page 1: 準備完了
                            }
                        }
                    });
                }
            });
        }
    };

    // 再試行コールバック
    let retry_workflow = start_workflow.clone();
    dialog.on_retry(move || {
        (retry_workflow)();
    });

    // ワークフロー開始
    (start_workflow)();

    dialog.run().map_err(|e| format!("UIループの実行に失敗しました: {e}"))?;
    Ok(())
}
