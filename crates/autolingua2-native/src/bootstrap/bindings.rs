use super::{core::Session, Context, Message, Phase};
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use std::path::Path;
use std::time::Duration;

#[pyclass]
pub struct CoreSession { session: Session }

#[pymethods]
impl CoreSession {
    #[new]
    #[pyo3(signature = (credential, development_root=None))]
    fn new(py: Python<'_>, credential: String, development_root: Option<String>) -> PyResult<Self> {
        py.detach(move || {
            let context = Context::new(development_root.as_deref().map(Path::new))?;
            Session::connect(context, credential).map(|session| Self { session })
        }).map_err(|err: std::io::Error| PyOSError::new_err(err.to_string()))
    }
    fn phase(&self, py: Python<'_>, phase_id: &str, message: String) -> PyResult<()> {
        let phase = Phase::parse(phase_id).map_err(os_error)?;
        py.detach(|| self.session.notify(Message::Phase(phase, message))).map_err(os_error)
    }
    fn ready(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.session.notify(Message::Ready)).map_err(os_error)
    }
    fn failed(&self, py: Python<'_>, message: String) -> PyResult<()> {
        py.detach(|| self.session.notify(Message::Failed(message))).map_err(os_error)
    }
    fn check(&self) -> PyResult<()> { self.session.check().map_err(os_error) }
    fn take_activation(&self) -> bool { self.session.take_activation() }
    fn take_source_update(&self) -> PyResult<Option<String>> { self.session.take_source_update().map_err(os_error) }
    fn prepare_restart(&self) -> PyResult<String> { self.session.prepare_restart().map_err(os_error) }
    fn wait_restart(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.session.wait_restart(Duration::from_secs(5))).map_err(os_error)
    }
    fn cancel_restart(&self) { self.session.cancel_restart(); }
    fn close(&mut self, py: Python<'_>) { py.detach(|| self.session.close()); }
}

fn os_error(err: std::io::Error) -> PyErr { PyOSError::new_err(err.to_string()) }

#[pyfunction]
pub fn update_status() -> (&'static str, &'static str) { super::update_status() }
