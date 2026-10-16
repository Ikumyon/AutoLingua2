use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;
use crate::platform;

pub fn is_running_from_temp(current_exe: &Path, project_root: &Path) -> bool {
    let temp_dir = project_root.join(".data").join("updates").join("temp_updater");
    if let (Ok(exe_canon), Ok(temp_canon)) = (
        platform::canonicalize_path(current_exe),
        platform::canonicalize_path(&temp_dir),
    ) {
        exe_canon.starts_with(temp_canon)
    } else {
        false
    }
}

pub fn handoff_to_temp_updater(
    project_root: &Path,
    forwarded_args: &[String],
) -> Result<(), String> {
    let current_exe = std::env::current_exe().map_err(|e| format!("実行ファイルの取得に失敗しました: {e}"))?;
    let temp_dir = project_root.join(".data").join("updates").join("temp_updater");
    fs::create_dir_all(&temp_dir).map_err(|e| format!("一時アップデーターフォルダの作成に失敗しました: {e}"))?;

    let exe_name = platform::updater_executable_name();
    let temp_exe = temp_dir.join(exe_name);

    fs::copy(&current_exe, &temp_exe).map_err(|e| {
        format!(
            "アップデーターの一時コピーに失敗しました ({} -> {}): {e}",
            current_exe.display(),
            temp_exe.display()
        )
    })?;

    let mut command = std::process::Command::new(&temp_exe);
    command.current_dir(project_root);
    command.args(forwarded_args);
    command.arg("--internal-apply");

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x00000008;
        command.creation_flags(DETACHED_PROCESS);
    }

    platform::reset_inherited_library_directory()
        .map_err(|e| format!("一時アップデーターのDLL検索先の初期化に失敗しました: {e}"))?;

    command
        .spawn()
        .map_err(|e| format!("一時アップデーターの起動に失敗しました: {e}"))?;

    // 元のアップデーターは即座に終了してファイルロックを解除
    std::process::exit(0);
}

pub fn find_update_content_root(extracted_dir: &Path) -> PathBuf {
    // もし解凍直下に単一のディレクトリ（例: AUTOlingua2-v0.2.0/）があり、
    // その中に core やランチャーがある場合は、その階層をルートとする
    if let Ok(entries) = fs::read_dir(extracted_dir) {
        let list: Vec<fs::DirEntry> = entries.flatten().collect();
        if list.len() == 1 {
            let candidate = list[0].path();
            if candidate.is_dir() {
                let launcher = candidate.join(platform::launcher_executable_name());
                let core = candidate.join("core");
                if launcher.exists() || core.exists() {
                    return candidate;
                }
            }
        }
    }
    extracted_dir.to_path_buf()
}

pub fn copy_recursive(src: &Path, dst: &Path) -> io::Result<()> {
    if !src.exists() {
        return Ok(());
    }
    if src.is_dir() {
        fs::create_dir_all(dst)?;
        for entry in fs::read_dir(src)? {
            let entry = entry?;
            let entry_path = entry.path();
            let dest_path = dst.join(entry.file_name());
            copy_recursive(&entry_path, &dest_path)?;
        }
    } else {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::copy(src, dst).map_err(|err| {
            io::Error::new(
                err.kind(),
                format!("{} -> {}: {err}", src.display(), dst.display()),
            )
        })?;
    }
    Ok(())
}

pub fn execute_apply<F>(
    project_root: &Path,
    extracted_dir: &Path,
    wait_pids: &[u32],
    mut log_fn: F,
) -> Result<(), String>
where
    F: FnMut(&str),
{
    log_fn("更新対象プロセスの終了待機を開始します");
    for &pid in wait_pids {
        if pid > 0 {
            log_fn(&format!("プロセス (PID {pid}) の終了を待機しています…"));
            let exited = platform::wait_for_process_exit(pid, Duration::from_secs(30))
                .map_err(|e| format!("プロセス監視エラー (PID {pid}): {e}"))?;
            if !exited {
                return Err(format!("プロセス (PID {pid}) が終了しなかったため、適用を中止しました"));
            }
        }
    }
    log_fn("すべての更新対象プロセスが終了しました");

    let content_root = find_update_content_root(extracted_dir);
    log_fn(&format!("新バージョンファイルの配置を開始します: {}", content_root.display()));

    copy_recursive(&content_root, project_root)
        .map_err(|e| format!("ファイルの配置・上書き置換に失敗しました: {e}"))?;

    log_fn("すべてのファイルを正常に更新・配置しました");

    // 新ランチャーの自動起動
    let launcher_path = project_root.join(platform::launcher_executable_name());
    log_fn(&format!("新しいランチャーを起動します: {}", launcher_path.display()));

    platform::spawn_launcher(&launcher_path)
        .map_err(|e| format!("新しいランチャーの起動に失敗しました: {e}"))?;

    log_fn("更新が正常に完了しました");
    Ok(())
}
