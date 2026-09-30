use super::security::verify_directory;
use std::io;
use std::path::PathBuf;

pub fn development_python() -> &'static str { ".venv/bin/python" }
pub fn log_directory() -> std::io::Result<PathBuf> {
    std::env::var_os("XDG_STATE_HOME").map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/state")))
        .map(|path| path.join("AUTOlingua2/logs"))
        .ok_or_else(|| std::io::Error::other("Log directory unavailable"))
}
pub fn runtime_root() -> io::Result<PathBuf> {
    if let Some(path) = std::env::var_os("XDG_RUNTIME_DIR") {
        let path = PathBuf::from(path);
        verify_directory(&path)?;
        return Ok(path);
    }
    Ok(std::env::temp_dir())
}
