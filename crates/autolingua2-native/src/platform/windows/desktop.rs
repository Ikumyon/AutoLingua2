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

#[cfg(feature = "python")]
pub fn system_voice_input_available() -> bool {
    true
}

#[cfg(feature = "python")]
pub fn start_system_voice_input() -> Result<(), String> {
    use windows_sys::Win32::System::Threading::GetCurrentProcessId;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        GetAsyncKeyState, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, VK_CONTROL, VK_H, VK_LWIN,
        VK_MENU, VK_RWIN, VK_SHIFT,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetForegroundWindow, GetWindowThreadProcessId,
    };

    // Do not send a system shortcut to another application or modify held keys.
    let mut foreground_pid = 0;
    unsafe {
        GetWindowThreadProcessId(GetForegroundWindow(), &mut foreground_pid);
        if foreground_pid != GetCurrentProcessId() {
            return Err("Focus AUTOlingua2 before starting voice input".into());
        }
        for key in [VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN, VK_H] {
            if GetAsyncKeyState(i32::from(key)) < 0 {
                return Err("Release keyboard keys before starting voice input".into());
            }
        }
    }
    let keyboard_input = |key, flags| INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT { wVk: key, wScan: 0, dwFlags: flags, time: 0, dwExtraInfo: 0 },
        },
    };
    let inputs = [
        keyboard_input(VK_LWIN, KEYEVENTF_EXTENDEDKEY),
        keyboard_input(VK_H, 0),
        keyboard_input(VK_H, KEYEVENTF_KEYUP),
        keyboard_input(VK_LWIN, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
    ];
    let input_size = std::mem::size_of::<INPUT>() as i32;
    let sent = unsafe { SendInput(inputs.len() as u32, inputs.as_ptr(), input_size) };
    if sent != inputs.len() as u32 {
        // Release any keys injected before a partial failure.
        if sent > 0 {
            unsafe { SendInput(2, inputs[2..].as_ptr(), input_size); }
        }
        return Err(format!("Could not open Windows voice input ({sent}/4 keyboard events sent)"));
    }
    Ok(())
}
