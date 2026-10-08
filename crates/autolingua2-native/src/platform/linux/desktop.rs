use std::path::Path;
#[cfg(feature = "python")]
use std::io::IsTerminal;

#[cfg(feature = "python")]
pub fn configure_desktop_integration(_app_id: &str) -> Result<(), String> {
    Ok(())
}

#[cfg(feature = "python")]
pub fn allocate_debug_console() -> (String, String) {
    if std::io::stderr().is_terminal() {
        ("existing".into(), String::new())
    } else {
        ("unavailable".into(), "No terminal attached; use the application log".into())
    }
}
pub fn open_folder(path: &Path) -> std::io::Result<()> {
    std::process::Command::new("xdg-open").arg(path).spawn()?;
    Ok(())
}

#[cfg(feature = "python")]
pub fn system_voice_input_available() -> bool {
    false
}

#[cfg(feature = "python")]
pub fn start_system_voice_input() -> Result<(), String> {
    Err("System voice input is unavailable; select a desktop voice input plugin".into())
}
