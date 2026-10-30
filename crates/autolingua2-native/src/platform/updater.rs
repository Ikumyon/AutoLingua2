use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use std::path::Path;
use std::process::{Command, Stdio};

use super::os_impl;

fn updater_command(root: &Path, detached: bool) -> std::io::Result<Command> {
    let name = os_impl::executable_name("autolingua-updater");
    let executable = [root.join("core"), root.join("target/release"), root.join("target/debug")]
        .into_iter()
        .map(|directory| directory.join(&name))
        .find(|path| path.is_file())
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound,
            "アップデーター実行ファイルが見つかりません。"))?;
    let mut command = Command::new(executable);
    command.current_dir(root).stdin(Stdio::null());
    os_impl::configure_updater_command(&mut command, detached);
    Ok(command)
}

#[pyfunction]
pub fn check_update(py: Python<'_>, project_root: String, current_version: String) -> PyResult<(i32, String, String)> {
    py.detach(|| {
        let output = updater_command(Path::new(&project_root), false)?
            .args(["check", "--project-root", &project_root, "--current-version", &current_version])
            .output()?;
        Ok((output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stdout).into_owned(),
            String::from_utf8_lossy(&output.stderr).into_owned()))
    }).map_err(|error: std::io::Error| PyOSError::new_err(error.to_string()))
}

#[pyfunction]
pub fn start_update(py: Python<'_>, project_root: String, arguments: Vec<String>) -> PyResult<()> {
    py.detach(|| {
        let mut child = updater_command(Path::new(&project_root), true)?
            .args(["gui", "--project-root", &project_root, "--parent-pid", &std::process::id().to_string()])
            .args(arguments)
            .stdout(Stdio::null()).stderr(Stdio::null())
            .spawn()?;
        // Unixでも子プロセスを回収し、UIの終了を待たせない。
        std::thread::spawn(move || { let _ = child.wait(); });
        Ok(())
    }).map_err(|error: std::io::Error| PyOSError::new_err(error.to_string()))
}
