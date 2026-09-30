use std::fs::File;
use std::io::{self, Read, Write};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{AsRawHandle, FromRawHandle};
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Security::Authorization::*;
use windows_sys::Win32::Security::Cryptography::{BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG};
use windows_sys::Win32::Security::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::Pipes::*;
use windows_sys::Win32::System::RemoteDesktop::ProcessIdToSessionId;
use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

fn wide(value: &std::ffi::OsStr) -> Vec<u16> { value.encode_wide().chain(Some(0)).collect() }

fn sid() -> io::Result<String> {
    unsafe {
        let mut token = null_mut();
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) == 0 {
            return Err(io::Error::last_os_error());
        }
        let token = File::from_raw_handle(token);
        let mut size = 0;
        GetTokenInformation(token.as_raw_handle(), TokenUser, null_mut(), 0, &mut size);
        if size == 0 { return Err(io::Error::last_os_error()); }
        // usize alignment is sufficient for TOKEN_USER and its SID buffer.
        let mut buffer = vec![0usize; (size as usize).div_ceil(std::mem::size_of::<usize>())];
        if GetTokenInformation(token.as_raw_handle(), TokenUser, buffer.as_mut_ptr().cast(), size, &mut size) == 0 {
            return Err(io::Error::last_os_error());
        }
        let user = &*buffer.as_ptr().cast::<TOKEN_USER>();
        let mut text = null_mut();
        if ConvertSidToStringSidW(user.User.Sid, &mut text) == 0 { return Err(io::Error::last_os_error()); }
        let mut length = 0;
        while *text.add(length) != 0 { length += 1; }
        let result = String::from_utf16_lossy(std::slice::from_raw_parts(text, length));
        LocalFree(text.cast());
        Ok(result)
    }
}

struct Security(PSECURITY_DESCRIPTOR);
impl Security {
    fn new() -> io::Result<Self> {
        let sddl = wide(std::ffi::OsStr::new(&format!("D:P(A;OICI;GA;;;{})", sid()?)));
        let mut descriptor = null_mut();
        if unsafe { ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.as_ptr(), 1, &mut descriptor, null_mut()) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(descriptor))
    }
    fn attributes(&self) -> SECURITY_ATTRIBUTES {
        SECURITY_ATTRIBUTES { nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: self.0, bInheritHandle: 0 }
    }
}
impl Drop for Security { fn drop(&mut self) { unsafe { LocalFree(self.0); } } }

pub fn identity() -> io::Result<String> {
    let mut session = 0;
    if unsafe { ProcessIdToSessionId(std::process::id(), &mut session) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(format!("{}:{session}", sid()?))
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

pub fn private_directory(path: &Path) -> io::Result<()> {
    let security = Security::new()?;
    let attributes = security.attributes();
    if unsafe { CreateDirectoryW(wide(path.as_os_str()).as_ptr(), &attributes) } == 0 {
        let err = io::Error::last_os_error();
        if err.raw_os_error() != Some(ERROR_ALREADY_EXISTS as i32) { return Err(err); }
    }
    use std::os::windows::fs::MetadataExt;
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(io::Error::other("Invalid IPC directory"));
    }
    Ok(())
}

pub fn random(bytes: &mut [u8]) -> io::Result<()> {
    if unsafe { BCryptGenRandom(null_mut(), bytes.as_mut_ptr(), bytes.len() as u32, BCRYPT_USE_SYSTEM_PREFERRED_RNG) } < 0 {
        return Err(io::Error::other("Cannot obtain bootstrap credentials"));
    }
    Ok(())
}

pub fn open_lock(path: &Path) -> io::Result<File> {
    std::fs::OpenOptions::new().read(true).write(true).create(true).truncate(false).open(path)
}

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

pub struct ProcessWatch(File);
impl ProcessWatch {
    pub fn open(pid: u32) -> io::Result<Self> {
        use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SYNCHRONIZE};
        let handle = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, pid) };
        if handle.is_null() { return Err(io::Error::last_os_error()); }
        Ok(Self(unsafe { File::from_raw_handle(handle) }))
    }
    pub fn alive(&self) -> io::Result<bool> {
        use windows_sys::Win32::System::Threading::WaitForSingleObject;
        match unsafe { WaitForSingleObject(self.0.as_raw_handle(), 0) } {
            WAIT_TIMEOUT => Ok(true),
            WAIT_OBJECT_0 => Ok(false),
            _ => Err(io::Error::last_os_error()),
        }
    }
}
