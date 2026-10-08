//! Linux implementation of the shared platform boundary.
mod desktop;
mod ipc;
mod paths;
mod process;
mod security;

pub use desktop::open_folder;
pub use ipc::{Listener, Stream};
pub use paths::{development_python, log_directory, runtime_root};
pub use process::{configure_core_command, executable_name, ProcessWatch};
pub use security::{identity, open_lock, private_directory, random};

#[cfg(feature = "python")]
pub use desktop::{allocate_debug_console, configure_desktop_integration};
#[cfg(feature = "python")]
pub use desktop::{system_voice_input_available, start_system_voice_input};
#[cfg(feature = "python")]
pub use process::{is_executable_plugin, configure_plugin_command, Group};
