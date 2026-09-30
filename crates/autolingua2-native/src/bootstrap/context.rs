use super::os;
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub struct Context {
    pub directory: PathBuf,
    pub name: String,
}

impl Context {
    pub fn new(development_root: Option<&Path>) -> io::Result<Self> {
        let identity = os::identity()?;
        let mode = match development_root {
            Some(root) => format!("development:{}", root.canonicalize()?.display()),
            None => "installed".into(),
        };
        // Stable across compiler versions; the hash is a name, never a credential.
        let hash = format!("{identity}:{mode}").bytes().fold(0xcbf29ce484222325u64,
            |hash, byte| (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3));
        let name = format!("{hash:016x}");
        let directory = match development_root {
            Some(root) => root.join(".runtime").join(&name),
            None => os::runtime_root()?.join(&name),
        };
        os::private_directory(&directory)?;
        Ok(Self { directory, name })
    }

    pub fn endpoint(&self, role: &str) -> PathBuf {
        self.directory.join(role)
    }

    pub fn lock(&self, role: &str) -> io::Result<Option<InstanceLock>> {
        let path = self.directory.join(format!("{role}.lock"));
        let file = os::open_lock(&path)?;
        match file.try_lock() {
            Ok(()) => Ok(Some(InstanceLock(file))),
            Err(std::fs::TryLockError::WouldBlock) => Ok(None),
            Err(std::fs::TryLockError::Error(err)) => Err(err),
        }
    }

    pub fn core_running(&self) -> io::Result<bool> {
        Ok(self.lock("core")?.is_none())
    }
}

// Lock files are never unlinked: doing so creates a second lock inode on Unix.
pub struct InstanceLock(#[allow(dead_code)] File);
