//! Owned subprocesses and bounded binary pipes exposed through an OS-neutral API.
use super::{bindings::register_group, os_impl};
use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

fn error(err: impl std::fmt::Display) -> PyErr { PyOSError::new_err(err.to_string()) }

#[pyclass(frozen)]
pub struct BinaryReader {
    pipe: Mutex<Option<BufReader<Box<dyn Read + Send>>>>,
}

#[pymethods]
impl BinaryReader {
    fn readline<'py>(&self, py: Python<'py>, limit: usize) -> PyResult<Bound<'py, PyBytes>> {
        if limit == 0 { return Err(PyValueError::new_err("Read limit must be positive")); }
        let bytes = py.detach(|| {
            let mut pipe = self.pipe.lock().map_err(error)?;
            let pipe = pipe.as_mut().ok_or_else(|| error("Pipe is closed"))?;
            let mut bytes = Vec::new();
            while bytes.len() < limit {
                let available = pipe.fill_buf().map_err(error)?;
                if available.is_empty() { break; }
                let count = available.len().min(limit - bytes.len());
                let data = &available[..count];
                let newline = data.iter().position(|byte| *byte == b'\n');
                let count = newline.map_or(count, |index| index + 1);
                bytes.extend_from_slice(&data[..count]);
                pipe.consume(count);
                if newline.is_some() { break; }
            }
            Ok::<_, PyErr>(bytes)
        })?;
        Ok(PyBytes::new(py, &bytes))
    }

    #[getter]
    fn closed(&self) -> PyResult<bool> {
        Ok(self.pipe.lock().map_err(error)?.is_none())
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| { self.pipe.lock().map_err(error)?.take(); Ok(()) })
    }
}

#[pyclass(frozen)]
pub struct BinaryWriter { pipe: Mutex<Option<ChildStdin>> }

#[pymethods]
impl BinaryWriter {
    fn write(&self, py: Python<'_>, data: Vec<u8>) -> PyResult<usize> {
        py.detach(|| {
            let mut pipe = self.pipe.lock().map_err(error)?;
            pipe.as_mut().ok_or_else(|| error("Pipe is closed"))?.write_all(&data).map_err(error)?;
            Ok(data.len())
        })
    }
    fn flush(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            self.pipe.lock().map_err(error)?.as_mut()
                .ok_or_else(|| error("Pipe is closed"))?.flush().map_err(error)
        })
    }
    #[getter]
    fn closed(&self) -> PyResult<bool> { Ok(self.pipe.lock().map_err(error)?.is_none()) }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| { self.pipe.lock().map_err(error)?.take(); Ok(()) })
    }
}

struct OwnedChild {
    child: Child,
    group: super::bindings::SharedGroup,
}

impl OwnedChild {
    fn close(&mut self) -> io::Result<()> {
        self.group.lock().map_err(|_| io::Error::other("Process group poisoned"))?.take();
        if self.child.try_wait()?.is_none() {
            if let Err(error) = self.child.kill() {
                // Closing the job/group may already have terminated the child.
                if self.child.try_wait()?.is_none() { return Err(error); }
            }
        }
        self.child.wait()?;
        Ok(())
    }
}

impl Drop for OwnedChild {
    fn drop(&mut self) { let _ = self.close(); }
}

#[pyclass(frozen)]
pub struct PluginProcess {
    process: Mutex<OwnedChild>,
    #[pyo3(get)]
    stdin: Py<BinaryWriter>,
    #[pyo3(get)]
    stdout: Py<BinaryReader>,
    #[pyo3(get)]
    stderr: Py<BinaryReader>,
}

#[pymethods]
impl PluginProcess {
    fn poll(&self, py: Python<'_>) -> PyResult<Option<i32>> {
        py.detach(|| {
            let status = self.process.lock().map_err(error)?.child.try_wait().map_err(error)?;
            Ok(status.map(|status| status.code().unwrap_or(-1)))
        })
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.process.lock().map_err(error)?.close().map_err(error))
    }
}

#[pyfunction]
pub fn start_plugin(py: Python<'_>, executable: String, args: Vec<String>, cwd: String) -> PyResult<PluginProcess> {
    let mut owned = py.detach(|| {
        if !os_impl::is_executable_plugin(Path::new(&executable)) {
            return Err(error("Plugin executable is unavailable"));
        }
        let mut command = Command::new(executable);
        command.args(args).current_dir(cwd)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
        os_impl::configure_plugin_command(&mut command);
        let mut child = command.spawn().map_err(error)?;
        match register_group(child.id()) {
            Ok(group) => Ok(OwnedChild { child, group }),
            Err(err) => {
                let _ = child.kill();
                let _ = child.wait();
                Err(err)
            }
        }
    })?;
    let stdin = owned.child.stdin.take().ok_or_else(|| error("Missing stdin"))?;
    let stdout = owned.child.stdout.take().ok_or_else(|| error("Missing stdout"))?;
    let stderr = owned.child.stderr.take().ok_or_else(|| error("Missing stderr"))?;
    Ok(PluginProcess {
        process: Mutex::new(owned),
        stdin: Py::new(py, BinaryWriter { pipe: Mutex::new(Some(stdin)) })?,
        stdout: Py::new(py, BinaryReader { pipe: Mutex::new(Some(BufReader::new(Box::new(stdout)))) })?,
        stderr: Py::new(py, BinaryReader { pipe: Mutex::new(Some(BufReader::new(Box::new(stderr)))) })?,
    })
}
