//! Shared OS boundary for both the launcher and the Python application.
#[cfg(windows)]
mod windows;
#[cfg(windows)]
use windows as os_impl;
#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
use linux as os_impl;
#[cfg(not(any(windows, target_os = "linux")))]
compile_error!("AUTOlingua2 supports Windows and Linux only");

pub(crate) use os_impl::bootstrap as bootstrap_os;
pub use os_impl::{executable_name, development_python, configure_core_command, log_directory, open_folder};

#[cfg(feature = "python")]
mod bindings;
#[cfg(feature = "python")]
pub use bindings::*;
