use pyo3::exceptions::PyOSError;
use super::os_impl;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex, Weak};

pub use super::child::{start_plugin, PluginProcess, BinaryReader, BinaryWriter};
pub(super) type SharedGroup = Arc<Mutex<Option<os_impl::Group>>>;
static GROUPS: Mutex<Vec<Weak<Mutex<Option<os_impl::Group>>>>> = Mutex::new(Vec::new());
static ABORTING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

pub fn abort_startup_plugins() {
    if let Ok(mut groups) = GROUPS.lock() {
        ABORTING.store(true, std::sync::atomic::Ordering::Release);
        for weak in groups.drain(..) {
            if let Some(group) = weak.upgrade() {
                if let Ok(mut group) = group.lock() { group.take(); }
            }
        }
    }
}

pub(super) fn register_group(pid: u32) -> PyResult<SharedGroup> {
    let mut groups = GROUPS.lock().map_err(|_| PyOSError::new_err("Process groups poisoned"))?;
    if ABORTING.load(std::sync::atomic::Ordering::Acquire) {
        return Err(PyOSError::new_err("Startup is being cancelled"));
    }
    let group = Arc::new(Mutex::new(Some(os_impl::Group::new(pid).map_err(PyOSError::new_err)?)));
    groups.retain(|group| group.strong_count() != 0);
    groups.push(Arc::downgrade(&group));
    Ok(group)
}

#[pyfunction]
pub fn configure_desktop_integration(app_id: &str) -> PyResult<()> {
    os_impl::configure_desktop_integration(app_id).map_err(PyOSError::new_err)
}

#[pyfunction]
pub fn system_voice_input_available() -> bool {
    os_impl::system_voice_input_available()
}

#[pyfunction]
pub fn start_system_voice_input() -> PyResult<()> {
    os_impl::start_system_voice_input().map_err(PyOSError::new_err)
}

#[pyfunction]
pub fn allocate_debug_console(py: Python<'_>) -> PyResult<(String, String)> {
    let result = os_impl::allocate_debug_console();
    #[cfg(windows)]
    if result.0 != "unavailable" {
        // CPython's windowed executable has no standard streams after AllocConsole.
        use pyo3::types::PyDict;
        let builtins = py.import("builtins")?;
        let sys = py.import("sys")?;
        let mut streams: Vec<Bound<'_, PyAny>> = Vec::new();
        for (name, mode) in [("CONIN$", "r"), ("CONOUT$", "w"), ("CONOUT$", "w")] {
            let kwargs = PyDict::new(py);
            kwargs.set_item("encoding", "utf-8")?;
            kwargs.set_item("buffering", 1)?;
            match builtins.call_method("open", (name, mode), Some(&kwargs)) {
                Ok(stream) => streams.push(stream),
                Err(error) => {
                    for stream in streams { let _ = stream.call_method0("close"); }
                    return Err(error);
                }
            }
        }
        for (name, stream) in ["stdin", "stdout", "stderr"].iter().zip(streams) {
            sys.setattr(*name, stream)?;
        }
    }
    #[cfg(not(windows))]
    let _ = py;
    Ok(result)
}

#[pyfunction]
pub fn plugin_platform_key() -> &'static str {
    #[cfg(windows)]
    { "windows" }
    #[cfg(target_os = "linux")]
    { "linux" }
}

#[pyfunction(name = "executable_name")]
pub fn executable_filename(name: &str) -> String { os_impl::executable_name(name) }

#[pyfunction]
pub fn qt_file_path(path: String) -> String {
    #[cfg(windows)]
    {
        if let Some(rest) = path.strip_prefix(r"\\?\UNC\") {
            return format!(r"\\{}", rest);
        }
        if let Some(rest) = path.strip_prefix(r"\\?\") {
            let bytes = rest.as_bytes();
            if bytes.len() >= 3 && bytes[0].is_ascii_alphabetic()
                && bytes[1] == b':' && bytes[2] == b'\\'
            {
                return rest.to_owned();
            }
        }
    }
    path
}

#[pyfunction(name = "open_folder")]
pub fn show_folder(py: Python<'_>, path: String) -> PyResult<()> {
    py.detach(|| {
        std::fs::create_dir_all(&path)?;
        os_impl::open_folder(Path::new(&path))
    }).map_err(|err: std::io::Error| PyOSError::new_err(err.to_string()))
}

#[pyfunction]
pub fn spawn_launcher(py: Python<'_>, command: Vec<String>, environment: HashMap<String, String>) -> PyResult<()> {
    py.detach(|| {
        let (executable, arguments) = command.split_first()
            .ok_or_else(|| std::io::Error::other("Missing launcher executable"))?;
        let mut command = Command::new(executable);
        command.args(arguments).env_clear().envs(environment)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        os_impl::configure_core_command(&mut command);
        let mut child = command.spawn()?;
        // Reap detached launchers on Unix without blocking the caller.
        std::thread::spawn(move || { let _ = child.wait(); });
        Ok(())
    }).map_err(|err: std::io::Error| PyOSError::new_err(err.to_string()))
}
