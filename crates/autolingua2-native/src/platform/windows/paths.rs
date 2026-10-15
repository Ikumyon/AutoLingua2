use std::ffi::OsString;
use std::path::{Component, Path, PathBuf, Prefix};
use std::io;

pub fn canonicalize_path(path: &Path) -> io::Result<PathBuf> {
    let canonical = path.canonicalize()?;
    let mut components = canonical.components();
    let Some(Component::Prefix(prefix)) = components.next() else { return Ok(canonical); };
    // Qt file URLs require DOS/UNC paths rather than Win32 verbatim prefixes.
    let mut normalized = match prefix.kind() {
        Prefix::VerbatimDisk(drive) => PathBuf::from(format!("{}:\\", char::from(drive))),
        Prefix::VerbatimUNC(server, share) => {
            let mut root = OsString::from(r"\\");
            root.push(server);
            root.push(r"\");
            root.push(share);
            PathBuf::from(root)
        }
        _ => return Ok(canonical),
    };
    normalized.push(components.as_path());
    Ok(normalized)
}

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
