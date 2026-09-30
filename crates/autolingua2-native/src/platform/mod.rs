//! Shared OS boundary for both the launcher and the Python application.
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

pub use os_impl::{executable_name, development_python, configure_core_command, log_directory, open_folder};

#[cfg(feature = "python")]
mod bindings;
#[cfg(feature = "python")]
pub use bindings::*;
