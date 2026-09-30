use pyo3::exceptions::PyOSError;
use super::os_impl;
use pyo3::prelude::*;
use std::path::Path;
use std::sync::{Arc, Mutex, Weak};

type SharedGroup = Arc<Mutex<Option<os_impl::Group>>>;
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

#[pyfunction]
pub fn configure_desktop_integration(app_id: &str) -> PyResult<()> {
    os_impl::configure_desktop_integration(app_id).map_err(PyOSError::new_err)
}

#[pyfunction]
pub fn allocate_debug_console() -> (String, String) {
    os_impl::allocate_debug_console()
}
#[pyfunction]
pub fn is_executable_plugin(path: &str) -> bool {
    os_impl::is_executable_plugin(Path::new(path))
}
#[pyfunction]
pub fn plugin_creation_flags() -> u32 { os_impl::plugin_creation_flags() }

#[pyclass]
pub struct ProcessGroup { group: SharedGroup }
#[pymethods]
impl ProcessGroup {
    #[new]
    fn new(pid: u32) -> PyResult<Self> {
        let mut groups = GROUPS.lock().map_err(|_| PyOSError::new_err("Process groups poisoned"))?;
        if ABORTING.load(std::sync::atomic::Ordering::Acquire) {
            return Err(PyOSError::new_err("Startup is being cancelled"));
        }
        let group = Arc::new(Mutex::new(Some(os_impl::Group::new(pid).map_err(PyOSError::new_err)?)));
        groups.retain(|group| group.strong_count() != 0);
        groups.push(Arc::downgrade(&group));
        Ok(Self { group })
    }
    fn close(&mut self) {
        if let Ok(mut group) = self.group.lock() { group.take(); }
    }
}
