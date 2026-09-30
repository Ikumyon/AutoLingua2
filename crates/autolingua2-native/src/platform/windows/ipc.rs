use super::security::{wide, Security};
use std::fs::File;
use std::io::{self, Read, Write};
use std::os::windows::io::{AsRawHandle, FromRawHandle};
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::Pipes::*;

fn pipe_name(path: &Path) -> io::Result<Vec<u16>> {
    let scope = path.parent().and_then(Path::file_name).ok_or_else(|| io::Error::other("Invalid endpoint"))?;
    let role = path.file_name().ok_or_else(|| io::Error::other("Invalid endpoint"))?;
    Ok(wide(std::ffi::OsStr::new(&format!(r"\\.\pipe\{}-{}", scope.to_string_lossy(), role.to_string_lossy()))))
}

pub struct Stream(File);
impl Stream {
    pub fn connect(path: &Path) -> io::Result<Self> {
        let name = pipe_name(path)?;
        let handle = unsafe { CreateFileW(name.as_ptr(), GENERIC_READ | GENERIC_WRITE, 0,
            null(), OPEN_EXISTING, 0, null_mut()) };
        if handle == INVALID_HANDLE_VALUE { return Err(io::Error::last_os_error()); }
        let file = unsafe { File::from_raw_handle(handle) };
        let mode = PIPE_READMODE_BYTE | PIPE_NOWAIT;
        if unsafe { SetNamedPipeHandleState(file.as_raw_handle(), &mode, null(), null()) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(file))
    }
}
impl Read for Stream {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        let mut available = 0;
        if unsafe { PeekNamedPipe(self.0.as_raw_handle(), null_mut(), 0, null_mut(), &mut available, null_mut()) } == 0 {
            return Err(io::Error::last_os_error());
        }
        if available == 0 { return Err(io::ErrorKind::WouldBlock.into()); }
        self.0.read(bytes)
    }
}
impl Write for Stream {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match self.0.write(bytes) {
            Ok(0) => Err(io::ErrorKind::WouldBlock.into()),
            result => result,
        }
    }
    fn flush(&mut self) -> io::Result<()> { Ok(()) }
}

pub struct Listener { pipe: Option<File>, path: PathBuf }
impl Listener {
    pub fn bind(path: &Path) -> io::Result<Self> {
        let mut listener = Self { pipe: None, path: path.into() };
        listener.create()?;
        Ok(listener)
    }
    fn create(&mut self) -> io::Result<()> {
        let security = Security::new()?;
        let attributes = security.attributes();
        let handle = unsafe { CreateNamedPipeW(pipe_name(&self.path)?.as_ptr(), PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES, 32768, 32768, 0, &attributes) };
        if handle == INVALID_HANDLE_VALUE { return Err(io::Error::last_os_error()); }
        self.pipe = Some(unsafe { File::from_raw_handle(handle) });
        Ok(())
    }
    pub fn accept(&mut self) -> io::Result<Option<Stream>> {
        if self.pipe.is_none() { self.create()?; }
        let pipe = self.pipe.as_ref().ok_or_else(|| io::Error::other("Missing listening pipe"))?;
        let connected = unsafe { ConnectNamedPipe(pipe.as_raw_handle(), null_mut()) } != 0;
        let code = unsafe { GetLastError() };
        if connected || code == ERROR_PIPE_CONNECTED {
            let stream = Stream(self.pipe.take().ok_or_else(|| io::Error::other("Missing connected pipe"))?);
            self.create()?;
            return Ok(Some(stream));
        }
        if code == ERROR_PIPE_LISTENING { return Ok(None); }
        if code == ERROR_NO_DATA {
            self.pipe.take();
            self.create()?;
            return Ok(None);
        }
        Err(io::Error::from_raw_os_error(code as i32))
    }
}
