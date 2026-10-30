//! Shared OS boundary for both the launcher and the Python application.
use std::io;
use std::path::PathBuf;

#[cfg(windows)]
pub(crate) mod windows;
#[cfg(windows)]
pub(crate) use windows as os_impl;
#[cfg(target_os = "linux")]
pub(crate) mod linux;
#[cfg(target_os = "linux")]
pub(crate) use linux as os_impl;
#[cfg(not(any(windows, target_os = "linux")))]
compile_error!("AUTOlingua2 supports Windows and Linux only");

pub use os_impl::{canonicalize_path, executable_name, development_python, configure_core_command, log_directory, open_folder};

pub fn runtime_root() -> io::Result<PathBuf> {
    if let Some(root) = std::env::var_os("AUTOLINGUA_DEVELOPMENT_ROOT") {
        return Ok(PathBuf::from(root).join(".data").join("runtime"));
    }
    let mut args = std::env::args_os();
    while let Some(arg) = args.next() {
        if arg == "--development-root" {
            let root = args.next().ok_or_else(|| io::Error::other("Missing development root"))?;
            return Ok(PathBuf::from(root).join(".data").join("runtime"));
        }
    }
    let executable = std::env::current_exe()?;
    let directory = executable.parent().ok_or_else(|| io::Error::other("Executable directory unavailable"))?;
    let root = if directory.file_name().and_then(|name| name.to_str()).is_some_and(|name| name.eq_ignore_ascii_case("core")) {
        directory.parent().ok_or_else(|| io::Error::other("Application directory unavailable"))?
    } else {
        directory
    };
    Ok(root.join(".data").join("runtime"))
}

#[cfg(feature = "python")]
pub mod bindings;
#[cfg(feature = "python")]
mod child;
#[cfg(feature = "python")]
mod updater;
#[cfg(feature = "python")]
pub use updater::{check_update, start_update};
#[cfg(feature = "python")]
pub use bindings::*;
