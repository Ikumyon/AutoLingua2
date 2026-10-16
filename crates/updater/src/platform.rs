use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub fn reset_inherited_library_directory() -> io::Result<()> {
    #[cfg(windows)]
    {
        // PyInstaller's DLL directory is inherited by children. Do not pass it
        // to the temporary updater, which must not lock files being replaced.
        if unsafe { windows_sys::Win32::System::LibraryLoader::SetDllDirectoryW(std::ptr::null()) } == 0 {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

#[cfg(windows)]
pub fn launcher_executable_name() -> &'static str {
    "AUTOlingua2.exe"
}

#[cfg(not(windows))]
pub fn launcher_executable_name() -> &'static str {
    "AUTOlingua2"
}

#[cfg(windows)]
pub fn updater_executable_name() -> &'static str {
    "autolingua-updater.exe"
}

#[cfg(not(windows))]
pub fn updater_executable_name() -> &'static str {
    "autolingua-updater"
}

pub fn canonicalize_path(path: &Path) -> io::Result<PathBuf> {
    autolingua2_native::platform::canonicalize_path(path)
}

pub fn wait_for_process_exit(pid: u32, timeout: Duration) -> io::Result<bool> {
    if pid == 0 {
        return Ok(true);
    }
    let start = std::time::Instant::now();
    let poll_interval = Duration::from_millis(100);

    #[cfg(windows)]
    {
        // autolingua2_native の ProcessWatch を利用
        match autolingua2_native::bootstrap::ProcessWatch::open(pid) {
            Ok(watch) => {
                while start.elapsed() < timeout {
                    match watch.alive() {
                        Ok(false) => return Ok(true),
                        Ok(true) => std::thread::sleep(poll_interval),
                        Err(_) => return Ok(true), // プロセスが既に存在しない場合
                    }
                }
                Ok(!watch.alive().unwrap_or(false))
            }
            Err(_) => Ok(true), // 開けない場合は既に終了している
        }
    }

    #[cfg(not(windows))]
    {
        while start.elapsed() < timeout {
            let res = unsafe { libc::kill(pid as i32, 0) };
            if res != 0 {
                return Ok(true);
            }
            std::thread::sleep(poll_interval);
        }
        let res = unsafe { libc::kill(pid as i32, 0) };
        Ok(res != 0)
    }
}

pub fn spawn_launcher(launcher_path: &Path) -> io::Result<()> {
    if !launcher_path.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("ランチャーが見つかりません: {}", launcher_path.display()),
        ));
    }
    let parent = launcher_path.parent().unwrap_or(Path::new("."));
    let mut command = std::process::Command::new(launcher_path);
    command.current_dir(parent);
    command.env("AUTOLINGUA_UPDATE_CLEANUP_PID", std::process::id().to_string());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_BREAKAWAY_FROM_JOB や通常起動
        const DETACHED_PROCESS: u32 = 0x00000008;
        command.creation_flags(DETACHED_PROCESS);
    }

    command.spawn()?;
    Ok(())
}
