use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use std::path::Path;

#[pyfunction]
fn configure(py: Python<'_>, settings: String, executable: String, enabled: bool, launcher: Vec<String>, icon: String) -> PyResult<()> {
    py.detach(|| super::configure(Path::new(&settings), Path::new(&executable), enabled, &launcher, &icon))
        .map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn notifications_available() -> bool { super::notification::available() }

#[pyfunction]
fn target_settings(settings: &str) -> PyResult<String> {
    super::target_settings(Path::new(settings)).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn save_target_settings(settings: &str, data: &str) -> PyResult<()> {
    super::save_target_settings(Path::new(settings), data).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn preview_sound(path: &str) -> PyResult<()> {
    super::notification::preview_sound(path).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn forget_target(settings: &str, project: &str) -> PyResult<()> {
    super::forget_target(Path::new(settings), project).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn running(settings: &str) -> PyResult<bool> {
    super::running(Path::new(settings)).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn status(settings: &str) -> PyResult<String> {
    super::status(Path::new(settings)).map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn snapshot(py: Python<'_>, settings: String, project: String) -> PyResult<String> {
    py.detach(|| super::snapshot(Path::new(&settings), &project))
        .map_err(|error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
fn acknowledge(settings: &str, project: &str, snapshot: &str) -> PyResult<()> {
    super::acknowledge(Path::new(settings), project, snapshot)
        .map_err(|error| PyOSError::new_err(error.to_string()))
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(configure, module)?)?;
    module.add_function(wrap_pyfunction!(notifications_available, module)?)?;
    module.add_function(wrap_pyfunction!(target_settings, module)?)?;
    module.add_function(wrap_pyfunction!(save_target_settings, module)?)?;
    module.add_function(wrap_pyfunction!(preview_sound, module)?)?;
    module.add_function(wrap_pyfunction!(forget_target, module)?)?;
    module.add_function(wrap_pyfunction!(running, module)?)?;
    module.add_function(wrap_pyfunction!(status, module)?)?;
    module.add_function(wrap_pyfunction!(snapshot, module)?)?;
    module.add_function(wrap_pyfunction!(acknowledge, module)?)?;
    Ok(())
}
