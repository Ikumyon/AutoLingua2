//! Linux process, console and bootstrap primitives.
#[cfg(feature = "python")]
use std::ffi::CString;
pub(crate) mod bootstrap;
#[cfg(feature = "python")]
use std::io::IsTerminal;
#[cfg(feature = "python")]
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};

#[cfg(feature = "python")]
pub fn allocate_debug_console() -> (String, String) {
    if std::io::stderr().is_terminal() {
        ("existing".into(), String::new())
    } else {
        ("unavailable".into(), "No terminal attached; use the application log".into())
    }
}
#[cfg(feature = "python")]
pub fn is_executable_plugin(path: &Path) -> bool {
    path.is_file() && CString::new(path.as_os_str().as_bytes())
        .is_ok_and(|path| unsafe { libc::access(path.as_ptr(), libc::X_OK) == 0 })
}
#[cfg(feature = "python")]
pub fn plugin_creation_flags() -> u32 { 0 }
#[cfg(feature = "python")]
pub struct Group { pid: Option<u32> }
#[cfg(feature = "python")]
impl Group {
    pub fn new(pid: u32) -> Result<Self, String> { Ok(Self { pid: Some(pid) }) }
    pub fn close(&mut self) {
        if let Some(pid) = self.pid.take() {
            unsafe { libc::kill(-(pid as i32), libc::SIGKILL); }
        }
    }
}
#[cfg(feature = "python")]
impl Drop for Group { fn drop(&mut self) { self.close(); } }

pub fn executable_name(name: &str) -> String { name.into() }
pub fn development_python() -> &'static str { ".venv/bin/python" }
pub fn configure_core_command(_command: &mut std::process::Command) {}
pub fn log_directory() -> std::io::Result<PathBuf> {
    std::env::var_os("XDG_STATE_HOME").map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/state")))
        .map(|path| path.join("AUTOlingua2/logs"))
        .ok_or_else(|| std::io::Error::other("Log directory unavailable"))
}
pub fn open_folder(path: &Path) -> std::io::Result<()> {
    std::process::Command::new("xdg-open").arg(path).spawn()?;
    Ok(())
}
