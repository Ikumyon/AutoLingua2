//! Windows process, console and bootstrap primitives.
use std::path::{Path, PathBuf};
pub(crate) mod bootstrap;
#[cfg(feature = "python")]
use std::ptr::null_mut;
#[cfg(feature = "python")]
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(feature = "python")]
use windows_sys::Win32::System::Console::{AllocConsole, AttachConsole, ATTACH_PARENT_PROCESS};
#[cfg(feature = "python")]
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, THREADENTRY32, TH32CS_SNAPTHREAD};
#[cfg(feature = "python")]
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
    JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE};
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
#[cfg(feature = "python")]
use windows_sys::Win32::System::Threading::{
    OpenProcess, OpenThread, ResumeThread, PROCESS_SET_QUOTA, PROCESS_TERMINATE,
    THREAD_SUSPEND_RESUME, CREATE_SUSPENDED};

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

#[cfg(feature = "python")]
pub fn is_executable_plugin(path: &Path) -> bool {
    path.is_file() && path.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("exe"))
}

#[cfg(feature = "python")]
pub fn plugin_creation_flags() -> u32 { CREATE_NO_WINDOW | CREATE_SUSPENDED }

#[cfg(feature = "python")]
pub struct Group { handle: usize }

#[cfg(feature = "python")]
impl Group {
    pub fn new(pid: u32) -> Result<Self, String> {
        unsafe {
            let job = CreateJobObjectW(null_mut(), std::ptr::null());
            if job.is_null() { return Err(std::io::Error::last_os_error().to_string()); }
            let group = Self { handle: job as usize };
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32) == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            if process.is_null() { return Err(std::io::Error::last_os_error().to_string()); }
            let assigned = AssignProcessToJobObject(job, process);
            let error = std::io::Error::last_os_error();
            CloseHandle(process);
            if assigned == 0 { return Err(error.to_string()); }
            // Popen created a suspended process. Resume only after job assignment.
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
            if snapshot == INVALID_HANDLE_VALUE {
                return Err(std::io::Error::last_os_error().to_string());
            }
            let mut entry: THREADENTRY32 = std::mem::zeroed();
            entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
            let mut found = false;
            let mut more = Thread32First(snapshot, &mut entry) != 0;
            while more {
                if entry.th32OwnerProcessID == pid {
                    let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                    if !thread.is_null() {
                        found = ResumeThread(thread) != u32::MAX;
                        CloseHandle(thread);
                    }
                    break;
                }
                more = Thread32Next(snapshot, &mut entry) != 0;
            }
            CloseHandle(snapshot);
            if !found { return Err("Could not resume plugin process".into()); }
            Ok(group)
        }
    }

    pub fn close(&mut self) {
        if self.handle != 0 {
            unsafe { CloseHandle(self.handle as HANDLE); }
            self.handle = 0;
        }
    }
}
#[cfg(feature = "python")]
impl Drop for Group { fn drop(&mut self) { self.close(); } }

pub fn executable_name(name: &str) -> String { format!("{name}.exe") }
pub fn development_python() -> &'static str { ".venv/Scripts/python.exe" }
pub fn configure_core_command(command: &mut std::process::Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(CREATE_NO_WINDOW);
}
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
pub fn open_folder(path: &Path) -> std::io::Result<()> {
    std::process::Command::new("explorer.exe").arg(path).spawn()?;
    Ok(())
}
