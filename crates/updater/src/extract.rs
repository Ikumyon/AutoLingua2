use std::fs::{self, File};
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use zip::ZipArchive;

pub fn extract_zip<F>(
    zip_path: &Path,
    extract_to: &Path,
    cancel_flag: &AtomicBool,
    mut progress_fn: F,
) -> Result<(), String>
where
    F: FnMut(u8, usize, usize, &str), // (percent, current_index, total_files, current_name)
{
    let file = File::open(zip_path).map_err(|e| format!("ZIPファイルのオープンに失敗しました: {e}"))?;
    let mut archive = ZipArchive::new(file).map_err(|e| format!("ZIPファイルの読み込みに失敗しました: {e}"))?;

    let total = archive.len();
    if total == 0 {
        return Ok(());
    }

    fs::create_dir_all(extract_to).map_err(|e| format!("展開先フォルダの作成に失敗しました: {e}"))?;

    for i in 0..total {
        if cancel_flag.load(Ordering::Acquire) {
            return Err("ユーザーにより解凍処理が中断されました".to_string());
        }

        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("ZIPエントリの読み込みに失敗しました ({i}): {e}"))?;

        let entry_name = entry.name().to_string();
        let enclosed = match entry.enclosed_name() {
            Some(path) => path.to_owned(),
            None => {
                // 安全でないパス（パストラバーサル等）はスキップ
                continue;
            }
        };

        let out_path = extract_to.join(&enclosed);

        if entry.is_dir() {
            fs::create_dir_all(&out_path)
                .map_err(|e| format!("ディレクトリの作成に失敗しました ({}): {e}", out_path.display()))?;
        } else {
            if let Some(parent) = out_path.parent() {
                fs::create_dir_all(parent)
                    .map_err(|e| format!("親ディレクトリの作成に失敗しました ({}): {e}", parent.display()))?;
            }

            let mut out_file = File::create(&out_path)
                .map_err(|e| format!("展開ファイルの作成に失敗しました ({}): {e}", out_path.display()))?;

            io::copy(&mut entry, &mut out_file)
                .map_err(|e| format!("ファイルデータの展開に失敗しました ({}): {e}", out_path.display()))?;

            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Some(mode) = entry.unix_mode() {
                    let _ = fs::set_permissions(&out_path, fs::Permissions::from_mode(mode));
                }
            }
        }

        let percent = (((i + 1) as f64 / total as f64) * 100.0).clamp(0.0, 100.0) as u8;
        progress_fn(percent, i + 1, total, &entry_name);
    }

    Ok(())
}
