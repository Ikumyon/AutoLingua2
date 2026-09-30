use autolingua2_native::platform;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::path::PathBuf;
use std::time::SystemTime;

pub fn log_directory() -> io::Result<PathBuf> {
    platform::log_directory()
}
pub(crate) fn log_file() -> io::Result<std::fs::File> {
    let directory = log_directory()?;
    std::fs::create_dir_all(&directory)?;
    OpenOptions::new().create(true).append(true).open(directory.join("launcher.log"))
}
pub fn record_failure(message: &str) {
    if let Ok(mut log) = log_file() { let _ = writeln!(log, "{:?} {message}", SystemTime::now()); }
}
pub fn open_logs() -> io::Result<()> {
    let path = log_directory()?;
    std::fs::create_dir_all(&path)?;
    platform::open_folder(&path)
}
