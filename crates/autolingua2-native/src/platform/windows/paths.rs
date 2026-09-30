use std::path::PathBuf;
use std::io;

pub fn development_python() -> &'static str { ".venv/Scripts/python.exe" }
pub fn log_directory() -> std::io::Result<PathBuf> {
    if let Some(dev_root) = std::env::var_os("AUTOLINGUA_DEVELOPMENT_ROOT") {
        return Ok(PathBuf::from(dev_root).join("logs"));
    }
    let mut args = std::env::args_os();
    while let Some(arg) = args.next() {
        if arg == "--development-root" {
            if let Some(val) = args.next() {
                return Ok(PathBuf::from(val).join("logs"));
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            return Ok(parent.join("logs"));
        }
    }
    Ok(PathBuf::from("logs"))
}
pub fn runtime_root() -> io::Result<PathBuf> {
    if let Some(dev_root) = std::env::var_os("AUTOLINGUA_DEVELOPMENT_ROOT") {
        return Ok(PathBuf::from(dev_root).join(".runtime"));
    }
    let mut args = std::env::args_os();
    while let Some(arg) = args.next() {
        if arg == "--development-root" {
            if let Some(val) = args.next() {
                return Ok(PathBuf::from(val).join(".runtime"));
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            return Ok(parent.join(".runtime"));
        }
    }
    Ok(PathBuf::from(".runtime"))
}
