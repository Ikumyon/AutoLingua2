use std::io;
use std::path::{Path, PathBuf};

pub fn canonicalize_path(path: &Path) -> io::Result<PathBuf> { path.canonicalize() }

pub fn development_python() -> &'static str { ".venv/bin/python" }
pub fn log_directory() -> std::io::Result<PathBuf> {
    std::env::var_os("XDG_STATE_HOME").map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/state")))
        .map(|path| path.join("AUTOlingua2/logs"))
        .ok_or_else(|| std::io::Error::other("Log directory unavailable"))
}
