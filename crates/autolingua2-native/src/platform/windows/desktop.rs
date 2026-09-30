use std::path::Path;
#[cfg(feature = "python")]
use windows_sys::Win32::Foundation::GetLastError;
#[cfg(feature = "python")]
use windows_sys::Win32::System::Console::{AllocConsole, AttachConsole, ATTACH_PARENT_PROCESS};
#[cfg(feature = "python")]
use windows_sys::Win32::UI::Shell::SetCurrentProcessExplicitAppUserModelID;
#[cfg(feature = "python")]
use std::os::windows::ffi::OsStrExt;

#[cfg(feature = "python")]
pub fn configure_desktop_integration(app_id: &str) -> Result<(), String> {
    let wide: Vec<u16> = std::ffi::OsStr::new(app_id).encode_wide().chain(Some(0)).collect();
    let hr = unsafe { SetCurrentProcessExplicitAppUserModelID(wide.as_ptr()) };
    if hr < 0 {
        return Err(format!("SetCurrentProcessExplicitAppUserModelID failed with HRESULT {hr:#x}"));
    }
    Ok(())
}

#[cfg(feature = "python")]
pub fn allocate_debug_console() -> (String, String) {
    unsafe {
        if AttachConsole(ATTACH_PARENT_PROCESS) != 0 {
            return ("attached".into(), String::new());
        }
        // ERROR_ACCESS_DENIED means this process already owns/uses a console.
        if GetLastError() == 5 {
            return ("existing".into(), String::new());
        }
        if AllocConsole() != 0 {
            ("owned".into(), String::new())
        } else {
            ("unavailable".into(), std::io::Error::last_os_error().to_string())
        }
    }
}

pub fn open_folder(path: &Path) -> std::io::Result<()> {
    std::process::Command::new("explorer.exe").arg(path).spawn()?;
    Ok(())
}
