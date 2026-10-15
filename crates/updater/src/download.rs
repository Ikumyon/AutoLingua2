use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone)]
pub struct DownloadProgress {
    pub percent: u8,
    pub downloaded_bytes: u64,
    pub total_bytes: u64,
    pub speed_bytes_per_sec: u64,
    pub remaining_secs: Option<u64>,
}

impl DownloadProgress {
    pub fn format_bytes(&self) -> String {
        fn to_human(bytes: u64) -> String {
            if bytes >= 1024 * 1024 * 1024 {
                format!("{:.1} GB", bytes as f64 / (1024.0 * 1024.0 * 1024.0))
            } else if bytes >= 1024 * 1024 {
                format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0))
            } else if bytes >= 1024 {
                format!("{:.1} KB", bytes as f64 / 1024.0)
            } else {
                format!("{bytes} B")
            }
        }
        if self.total_bytes > 0 {
            format!("{} / {}", to_human(self.downloaded_bytes), to_human(self.total_bytes))
        } else {
            to_human(self.downloaded_bytes)
        }
    }

    pub fn format_speed_and_time(&self) -> String {
        fn to_speed(speed: u64) -> String {
            if speed >= 1024 * 1024 {
                format!("{:.1} MB/s", speed as f64 / (1024.0 * 1024.0))
            } else if speed >= 1024 {
                format!("{:.1} KB/s", speed as f64 / 1024.0)
            } else {
                format!("{speed} B/s")
            }
        }
        let speed_str = to_speed(self.speed_bytes_per_sec);
        if let Some(secs) = self.remaining_secs {
            if secs >= 60 {
                let mins = secs / 60;
                let rem_secs = secs % 60;
                format!("{speed_str} (残り {mins}分{rem_secs}秒)")
            } else {
                format!("{speed_str} (残り {secs}秒)")
            }
        } else {
            speed_str
        }
    }
}

pub fn download_file<F>(
    url: &str,
    target_path: &Path,
    cancel_flag: &AtomicBool,
    mut progress_fn: F,
) -> Result<(), String>
where
    F: FnMut(DownloadProgress),
{
    if let Some(parent) = target_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("保存先フォルダの作成に失敗しました: {e}"))?;
    }

    let response = ureq::get(url)
        .set("User-Agent", "AUTOlingua2-Updater")
        .call()
        .map_err(|e| format!("ダウンロード接続に失敗しました: {e}"))?;

    let total_bytes: u64 = response
        .header("Content-Length")
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let mut reader = response.into_reader();
    let mut file = File::create(target_path).map_err(|e| format!("保存先ファイルの作成に失敗しました: {e}"))?;

    let mut buffer = [0u8; 64 * 1024];
    let mut downloaded_bytes: u64 = 0;

    let start_time = Instant::now();
    let mut last_progress_time = Instant::now();
    let mut bytes_since_last = 0u64;
    let mut current_speed = 0u64;

    loop {
        if cancel_flag.load(Ordering::Acquire) {
            drop(file);
            let _ = std::fs::remove_file(target_path);
            return Err("ユーザーによりダウンロードがキャンセルされました".to_string());
        }

        let n = reader
            .read(&mut buffer)
            .map_err(|e| format!("データの受信中にエラーが発生しました: {e}"))?;
        if n == 0 {
            break;
        }

        file.write_all(&buffer[..n])
            .map_err(|e| format!("ファイルへの書き込みに失敗しました: {e}"))?;

        downloaded_bytes += n as u64;
        bytes_since_last += n as u64;

        let elapsed = last_progress_time.elapsed();
        if elapsed >= Duration::from_millis(500) || (total_bytes > 0 && downloaded_bytes == total_bytes) {
            let secs = elapsed.as_secs_f64();
            if secs > 0.0 {
                current_speed = (bytes_since_last as f64 / secs) as u64;
            }
            bytes_since_last = 0;
            last_progress_time = Instant::now();

            let remaining_secs = if current_speed > 0 && total_bytes > downloaded_bytes {
                Some((total_bytes - downloaded_bytes) / current_speed)
            } else {
                None
            };

            let percent = if total_bytes > 0 {
                ((downloaded_bytes as f64 / total_bytes as f64) * 100.0).clamp(0.0, 100.0) as u8
            } else {
                0
            };

            progress_fn(DownloadProgress {
                percent,
                downloaded_bytes,
                total_bytes,
                speed_bytes_per_sec: current_speed,
                remaining_secs,
            });
        }
    }

    file.flush().map_err(|e| format!("ファイル書き込みのフラッシュに失敗しました: {e}"))?;

    // 完了通知
    let overall_elapsed = start_time.elapsed().as_secs_f64();
    let avg_speed = if overall_elapsed > 0.0 {
        (downloaded_bytes as f64 / overall_elapsed) as u64
    } else {
        0
    };

    progress_fn(DownloadProgress {
        percent: 100,
        downloaded_bytes,
        total_bytes: downloaded_bytes,
        speed_bytes_per_sec: avg_speed,
        remaining_secs: Some(0),
    });

    Ok(())
}

pub fn verify_sha256(file_path: &Path, expected_hex: &str) -> Result<bool, String> {
    let mut file = File::open(file_path).map_err(|e| format!("ファイルの検証オープンに失敗しました: {e}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];

    loop {
        let n = file
            .read(&mut buffer)
            .map_err(|e| format!("ハッシュ計算中の読み込みに失敗しました: {e}"))?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }

    let result = hasher.finalize();
    let calculated = hex::encode(result);

    Ok(calculated.eq_ignore_ascii_case(expected_hex.trim()))
}
