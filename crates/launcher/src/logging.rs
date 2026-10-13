use autolingua2_native::platform;
use chrono::Local;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::SystemTime;

static CURRENT_LOG: OnceLock<PathBuf> = OnceLock::new();

pub fn log_directory() -> io::Result<PathBuf> {
    platform::log_directory()
}

fn clean_old_logs(folder: &Path, keep: usize) {
    if let Ok(entries) = fs::read_dir(folder) {
        let mut logs: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.starts_with("launcher_") && n.ends_with(".log"))
                    .unwrap_or(false)
            })
            .collect();
        logs.sort();
        if logs.len() > keep {
            for old in &logs[..logs.len() - keep] {
                let _ = fs::remove_file(old);
            }
        }
    }
}

pub(crate) fn current_log_path() -> io::Result<PathBuf> {
    if let Some(path) = CURRENT_LOG.get() {
        return Ok(path.clone());
    }
    let directory = log_directory()?;
    fs::create_dir_all(&directory)?;
    clean_old_logs(&directory, 10);
    let timestamp = Local::now().format("%Y-%m-%d_%H%M%S");
    let path = directory.join(format!("launcher_{timestamp}.log"));
    let _ = CURRENT_LOG.set(path.clone());
    Ok(path)
}

pub(crate) fn log_file() -> io::Result<std::fs::File> {
    let path = current_log_path()?;
    OpenOptions::new().create(true).append(true).open(path)
}

pub fn record_failure(message: &str) {
    if let Ok(mut log) = log_file() {
        let _ = writeln!(log, "{:?} {message}", SystemTime::now());
    }
}

pub fn open_logs() -> io::Result<()> {
    let path = log_directory()?;
    fs::create_dir_all(&path)?;
    platform::open_folder(&path)
}
