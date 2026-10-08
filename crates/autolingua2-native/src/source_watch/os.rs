use std::io;
use std::path::Path;
use std::process::Command;

#[cfg(windows)]
mod implementation {
    use super::*;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::process::CommandExt;
    use windows_sys::Win32::Foundation::{HANDLE, INVALID_HANDLE_VALUE, WAIT_OBJECT_0};
    use windows_sys::Win32::Storage::FileSystem::{
        FindFirstChangeNotificationW, FindNextChangeNotification, FindCloseChangeNotification,
        MoveFileExW, FILE_NOTIFY_CHANGE_FILE_NAME, FILE_NOTIFY_CHANGE_DIR_NAME,
        FILE_NOTIFY_CHANGE_LAST_WRITE, FILE_NOTIFY_CHANGE_SIZE, MOVEFILE_REPLACE_EXISTING,
        MOVEFILE_WRITE_THROUGH,
    };
    use windows_sys::Win32::System::Threading::{WaitForSingleObject, CREATE_NO_WINDOW, DETACHED_PROCESS};

    fn wide(path: &Path) -> Vec<u16> { path.as_os_str().encode_wide().chain(Some(0)).collect() }

    pub fn replace(from: &Path, to: &Path) -> io::Result<()> {
        if unsafe { MoveFileExW(wide(from).as_ptr(), wide(to).as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    pub fn detach(command: &mut Command) { command.creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS); }

    pub fn autostart(settings: &Path, executable: &Path, enabled: bool) -> io::Result<()> {
        let mut command = Command::new("reg.exe");
        let key = "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run";
        if enabled {
            command.args(["add", key, "/v", "AUTOlingua2SourceWatcher", "/t", "REG_SZ", "/d"])
                .arg(format!("\"{}\" \"{}\"", executable.display(), settings.display())).arg("/f");
        } else {
            // Absence is already the requested state; query before deleting.
            let mut query = Command::new("reg.exe");
            query.args(["query", key, "/v", "AUTOlingua2SourceWatcher"]);
            detach(&mut query);
            if !query.output()?.status.success() { return Ok(()); }
            command.args(["delete", key, "/v", "AUTOlingua2SourceWatcher", "/f"]);
        }
        detach(&mut command);
        let output = command.output()?;
        if !output.status.success() { return Err(io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned())); }
        Ok(())
    }

    pub struct Notification(HANDLE);

    impl Notification {
        pub fn new(root: &Path, check_cancelled: &mut impl FnMut() -> io::Result<()>) -> io::Result<Self> {
            check_cancelled()?;
            let handle = unsafe { FindFirstChangeNotificationW(wide(root).as_ptr(), 1,
                FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME | FILE_NOTIFY_CHANGE_LAST_WRITE | FILE_NOTIFY_CHANGE_SIZE) };
            if handle == INVALID_HANDLE_VALUE { return Err(io::Error::last_os_error()); }
            Ok(Self(handle))
        }

        pub fn changed(&mut self) -> io::Result<bool> {
            if unsafe { WaitForSingleObject(self.0, 0) } != WAIT_OBJECT_0 { return Ok(false); }
            if unsafe { FindNextChangeNotification(self.0) } == 0 { return Err(io::Error::last_os_error()); }
            Ok(true)
        }
    }

    impl Drop for Notification {
        fn drop(&mut self) { unsafe { FindCloseChangeNotification(self.0); } }
    }
}

#[cfg(target_os = "linux")]
mod implementation {
    use super::*;
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::process::CommandExt;

    pub fn replace(from: &Path, to: &Path) -> io::Result<()> { std::fs::rename(from, to) }

    pub fn detach(command: &mut Command) {
        unsafe { command.pre_exec(|| { if libc::setsid() == -1 { return Err(io::Error::last_os_error()); } Ok(()) }); }
    }

    pub fn autostart(settings: &Path, executable: &Path, enabled: bool) -> io::Result<()> {
        let base = std::env::var_os("XDG_CONFIG_HOME").map(std::path::PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|home| std::path::PathBuf::from(home).join(".config")))
            .ok_or_else(|| io::Error::other("Missing user configuration directory"))?;
        let path = base.join("autostart/autolingua-source-watcher.desktop");
        if enabled {
            std::fs::create_dir_all(path.parent().ok_or_else(|| io::Error::other("Missing autostart parent"))?)?;
            let quote = |path: &Path| format!("\"{}\"", path.to_string_lossy().replace('\\', "\\\\").replace('"', "\\\"").replace('`', "\\`").replace('$', "\\$").replace('%', "%%"));
            std::fs::write(path, format!("[Desktop Entry]\nType=Application\nName=AUTOlingua2 Source Watcher\nExec={} {}\nTerminal=false\n", quote(executable), quote(settings)))?;
        } else {
            match std::fs::remove_file(path) {
                Ok(()) => (),
                Err(error) if error.kind() == io::ErrorKind::NotFound => (),
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }

    pub struct Notification(i32);

    impl Notification {
        pub fn new(root: &Path, check_cancelled: &mut impl FnMut() -> io::Result<()>) -> io::Result<Self> {
            check_cancelled()?;
            let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
            if fd < 0 { return Err(io::Error::last_os_error()); }
            let result = Self(fd);
            let mut directories = vec![root.to_path_buf()];
            while let Some(directory) = directories.pop() {
                check_cancelled()?;
                let name = CString::new(directory.as_os_str().as_bytes()).map_err(io::Error::other)?;
                if unsafe { libc::inotify_add_watch(fd, name.as_ptr(), libc::IN_CREATE | libc::IN_DELETE | libc::IN_MOVED_FROM | libc::IN_MOVED_TO | libc::IN_CLOSE_WRITE | libc::IN_DELETE_SELF | libc::IN_MOVE_SELF) } < 0 {
                    return Err(io::Error::last_os_error());
                }
                for entry in std::fs::read_dir(directory)? {
                    let entry = entry?;
                    if entry.file_type()?.is_dir() { directories.push(entry.path()); }
                }
            }
            Ok(result)
        }

        pub fn changed(&mut self) -> io::Result<bool> {
            let mut buffer = [0u8; 8192];
            let count = unsafe { libc::read(self.0, buffer.as_mut_ptr().cast(), buffer.len()) };
            if count >= 0 { return Ok(count > 0); }
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::WouldBlock { return Ok(false); }
            Err(error)
        }
    }

    impl Drop for Notification {
        fn drop(&mut self) { unsafe { libc::close(self.0); } }
    }
}

pub use implementation::*;
