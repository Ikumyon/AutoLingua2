use std::fs::{self, DirBuilder, File};
use std::io::{self, Read, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};

pub fn identity() -> io::Result<String> {
    let session = std::env::var("XDG_SESSION_ID")
        .or_else(|_| std::env::var("WAYLAND_DISPLAY"))
        .or_else(|_| std::env::var("DISPLAY"))
        .unwrap_or_else(|_| unsafe { libc::getsid(0) }.to_string());
    Ok(format!("{}:{session}", unsafe { libc::geteuid() }))
}

pub fn runtime_root() -> io::Result<PathBuf> {
    if let Some(path) = std::env::var_os("XDG_RUNTIME_DIR") {
        let path = PathBuf::from(path);
        verify_directory(&path)?;
        return Ok(path);
    }
    Ok(std::env::temp_dir())
}

fn verify_directory(path: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0 {
        return Err(io::Error::other("IPC directory must be owned by this user with mode 0700"));
    }
    Ok(())
}

pub fn private_directory(path: &Path) -> io::Result<()> {
    match DirBuilder::new().mode(0o700).create(path) {
        Ok(()) => (),
        Err(err) if err.kind() == io::ErrorKind::AlreadyExists => (),
        Err(err) => return Err(err),
    }
    verify_directory(path)
}

pub fn random(bytes: &mut [u8]) -> io::Result<()> {
    File::open("/dev/urandom")?.read_exact(bytes)
}

pub fn open_lock(path: &Path) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    std::fs::OpenOptions::new().read(true).write(true).create(true).truncate(false)
        .mode(0o600).custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path)
}

pub struct Stream(UnixStream);
impl Stream {
    pub fn connect(path: &Path) -> io::Result<Self> {
        let stream = UnixStream::connect(path)?;
        stream.set_nonblocking(true)?;
        Ok(Self(stream))
    }
}
impl Read for Stream {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> { self.0.read(bytes) }
}
impl Write for Stream {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> { self.0.write(bytes) }
    fn flush(&mut self) -> io::Result<()> { Ok(()) }
}

pub struct Listener { listener: UnixListener, path: PathBuf }
impl Listener {
    // Caller must hold the corresponding process lock before removing a stale endpoint.
    pub fn bind(path: &Path) -> io::Result<Self> {
        match fs::remove_file(path) {
            Ok(()) => (),
            Err(err) if err.kind() == io::ErrorKind::NotFound => (),
            Err(err) => return Err(err),
        }
        let listener = UnixListener::bind(path)?;
        listener.set_nonblocking(true)?;
        Ok(Self { listener, path: path.into() })
    }
    pub fn accept(&mut self) -> io::Result<Option<Stream>> {
        match self.listener.accept() {
            Ok((stream, _)) => {
                stream.set_nonblocking(true)?;
                Ok(Some(Stream(stream)))
            }
            Err(err) if err.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(err) => Err(err),
        }
    }
}
impl Drop for Listener {
    fn drop(&mut self) { let _ = fs::remove_file(&self.path); }
}

pub struct ProcessWatch(std::os::fd::OwnedFd);
impl ProcessWatch {
    pub fn open(pid: u32) -> io::Result<Self> {
        use std::os::fd::FromRawFd;
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
        if fd < 0 { return Err(io::Error::last_os_error()); }
        Ok(Self(unsafe { std::os::fd::OwnedFd::from_raw_fd(fd as i32) }))
    }
    pub fn alive(&self) -> io::Result<bool> {
        use std::os::fd::AsRawFd;
        let mut fd = libc::pollfd { fd: self.0.as_raw_fd(), events: libc::POLLIN, revents: 0 };
        match unsafe { libc::poll(&mut fd, 1, 0) } {
            -1 => Err(io::Error::last_os_error()),
            0 => Ok(true),
            _ => Ok(false),
        }
    }
}
