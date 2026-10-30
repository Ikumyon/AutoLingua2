use std::io;
#[cfg(feature = "python")]
use std::ffi::CString;
#[cfg(feature = "python")]
use std::os::unix::ffi::OsStrExt;
#[cfg(feature = "python")]
use std::path::Path;

#[cfg(feature = "python")]
pub fn is_executable_plugin(path: &Path) -> bool {
    path.is_file() && CString::new(path.as_os_str().as_bytes())
        .is_ok_and(|path| unsafe { libc::access(path.as_ptr(), libc::X_OK) == 0 })
}
#[cfg(feature = "python")]
pub fn configure_plugin_command(command: &mut std::process::Command) {
    use std::os::unix::process::CommandExt;
    // A dedicated process group lets cancellation terminate descendants too.
    command.process_group(0);
}
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
#[cfg(feature = "python")]
pub fn configure_updater_command(_command: &mut std::process::Command, _detached: bool) {}
pub fn configure_core_command(command: &mut std::process::Command) {
    // 明示されたQtの入力方式を優先し、なければOS側の指定に合わせる。
    let selected = std::env::var("QT_IM_MODULE")
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
        .or_else(|| {
            match std::env::var("XMODIFIERS").ok()?.trim() {
                "@im=fcitx" => Some("fcitx".to_owned()),
                "@im=ibus" => Some("ibus".to_owned()),
                _ => None,
            }
        });
    if let Some(selected) = selected {
        // 子プロセスだけに適用し、Qt初期化前に両変数の競合を解消する。
        command.env("QT_IM_MODULE", &selected).env("QT_IM_MODULES", &selected);
    }
}
pub struct ProcessWatch(std::os::fd::OwnedFd);
impl ProcessWatch {
    pub fn open(pid: u32) -> io::Result<Self> {
        use std::os::fd::FromRawFd;
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
        if fd < 0 { return Err(io::Error::last_os_error()); }
        Ok(Self(unsafe { std::os::fd::OwnedFd::from_raw_fd(fd as i32) }))
    }
    pub fn alive(&self) -> io::Result<bool> {
        use std::os::fd::AsRawFd;
        let mut fd = libc::pollfd { fd: self.0.as_raw_fd(), events: libc::POLLIN, revents: 0 };
        match unsafe { libc::poll(&mut fd, 1, 0) } {
            -1 => Err(io::Error::last_os_error()),
            0 => Ok(true),
            _ => Ok(false),
        }
    }
}
