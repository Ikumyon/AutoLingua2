//! The only process boundary protocol. No application/domain operations belong here.
use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

use crate::platform::bootstrap_os as os;
pub use os::{Listener, Stream, ProcessWatch};

pub mod core;
#[cfg(test)]
mod integration_tests;
#[cfg(feature = "python")]
pub mod bindings;

pub const MAX_FRAME: usize = 16 * 1024;
pub const UPDATE_UNAVAILABLE: &str = "更新機能は未実装です（配信予定: GitHub Releases）";

pub fn update_status() -> (&'static str, &'static str) {
    ("unavailable", UPDATE_UNAVAILABLE)
}

pub fn error(message: impl std::fmt::Display) -> io::Error {
    io::Error::other(message.to_string())
}

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

pub fn token() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    os::random(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

pub fn valid_token(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_hexdigit())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Phase { Diagnostics, Modules, Plugins, Settings, Window }

impl Phase {
    pub fn parse(id: &str) -> io::Result<Self> {
        match id {
            "diagnostics" => Ok(Self::Diagnostics), "modules" => Ok(Self::Modules),
            "plugins" => Ok(Self::Plugins), "settings" => Ok(Self::Settings),
            "window" => Ok(Self::Window), _ => Err(error("Unknown startup phase")),
        }
    }
    pub fn id(self) -> &'static str {
        match self {
            Self::Diagnostics => "diagnostics", Self::Modules => "modules",
            Self::Plugins => "plugins", Self::Settings => "settings", Self::Window => "window",
        }
    }
    pub fn progress(self) -> f32 { self as u8 as f32 / 5.0 }
}

#[derive(Default)]
pub struct StartupProgress { current: Option<Phase> }
impl StartupProgress {
    /// Returns true only for a newly reached phase, independently of its display text.
    pub fn advance(&mut self, phase: Phase) -> io::Result<bool> {
        if self.current.is_some_and(|current| phase < current) {
            return Err(error("Startup phase moved backwards"));
        }
        let changed = self.current != Some(phase);
        self.current = Some(phase);
        Ok(changed)
    }
    pub fn finish(&self) -> io::Result<f32> {
        if self.current != Some(Phase::Window) { return Err(error("READY before window initialization")); }
        Ok(1.0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Message {
    Hello(String), Phase(Phase, String), Ready, Failed(String), Ping, Ack,
    Activate, Restart(String), Cancel,
}

impl Message {
    pub fn encode(&self) -> io::Result<Vec<u8>> {
        let phase_payload = match self {
            Self::Phase(phase, text) if !text.is_empty() => format!("{}\n{text}", phase.id()),
            Self::Phase(_, _) => return Err(error("Empty startup phase description")),
            _ => String::new(),
        };
        let (kind, text) = match self {
            Self::Hello(s) => (1, s.as_str()), Self::Phase(_, _) => (2, phase_payload.as_str()),
            Self::Ready => (3, ""), Self::Failed(s) => (4, s.as_str()),
            Self::Ping => (5, ""), Self::Ack => (6, ""), Self::Activate => (7, ""),
            Self::Restart(s) => (8, s.as_str()), Self::Cancel => (9, ""),
        };
        let length = 2 + text.len();
        if length > MAX_FRAME { return Err(error("IPC message too large")); }
        let mut data = Vec::with_capacity(4 + length);
        data.extend_from_slice(&(length as u32).to_le_bytes());
        data.extend_from_slice(&[1, kind]);
        data.extend_from_slice(text.as_bytes());
        Ok(data)
    }

    fn decode(data: &[u8]) -> io::Result<Self> {
        if data.len() < 2 || data[0] != 1 { return Err(error("Unsupported IPC version")); }
        let text = std::str::from_utf8(&data[2..]).map_err(error)?;
        match data[1] {
            1 if valid_token(text) => Ok(Self::Hello(text.into())),
            2 => {
                let (id, description) = text.split_once('\n').ok_or_else(|| error("Missing startup phase ID"))?;
                if description.is_empty() { return Err(error("Empty startup phase description")); }
                Ok(Self::Phase(Phase::parse(id)?, description.into()))
            }
            4 if !text.is_empty() => Ok(Self::Failed(text.into())),
            8 if valid_token(text) => Ok(Self::Restart(text.into())),
            3 if text.is_empty() => Ok(Self::Ready),
            5 if text.is_empty() => Ok(Self::Ping),
            6 if text.is_empty() => Ok(Self::Ack),
            7 if text.is_empty() => Ok(Self::Activate),
            9 if text.is_empty() => Ok(Self::Cancel),
            _ => Err(error("Invalid IPC message")),
        }
    }
}

pub struct Connection {
    stream: Stream,
    buffer: Vec<u8>,
}

impl Connection {
    pub fn new(stream: Stream) -> Self { Self { stream, buffer: Vec::new() } }

    pub fn connect(path: &Path, timeout: Duration) -> io::Result<Self> {
        let deadline = Instant::now() + timeout;
        loop {
            match Stream::connect(path) {
                Ok(stream) => return Ok(Self::new(stream)),
                Err(err) if Instant::now() >= deadline => return Err(err),
                Err(_) => thread::sleep(Duration::from_millis(10)),
            }
        }
    }

    pub fn send(&mut self, message: &Message) -> io::Result<()> {
        let data = message.encode()?;
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut position = 0;
        while position < data.len() {
            match self.stream.write(&data[position..]) {
                Ok(0) => return Err(error("IPC disconnected while writing")),
                Ok(n) => position += n,
                Err(err) if err.kind() == io::ErrorKind::WouldBlock && Instant::now() < deadline =>
                    thread::sleep(Duration::from_millis(5)),
                Err(err) => return Err(err),
            }
        }
        Ok(())
    }

    pub fn poll(&mut self) -> io::Result<Option<Message>> {
        loop {
            if self.buffer.len() >= 4 {
                let length = u32::from_le_bytes(self.buffer[..4].try_into().map_err(error)?) as usize;
                if !(2..=MAX_FRAME).contains(&length) { return Err(error("Invalid IPC frame length")); }
                if self.buffer.len() >= length + 4 {
                    let message = Message::decode(&self.buffer[4..length + 4])?;
                    self.buffer.drain(..length + 4);
                    return Ok(Some(message));
                }
            }
            let mut bytes = [0u8; 4096];
            match self.stream.read(&mut bytes) {
                Ok(0) => return Err(error("IPC disconnected")),
                Ok(n) => self.buffer.extend_from_slice(&bytes[..n]),
                Err(err) if err.kind() == io::ErrorKind::WouldBlock => return Ok(None),
                Err(err) => return Err(err),
            }
        }
    }

    pub fn receive(&mut self, timeout: Duration) -> io::Result<Message> {
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(message) = self.poll()? { return Ok(message); }
            if Instant::now() >= deadline { return Err(error("IPC response timed out")); }
            thread::sleep(Duration::from_millis(5));
        }
    }

    pub fn request(&mut self, message: &Message) -> io::Result<()> {
        self.send(message)?;
        match self.receive(Duration::from_secs(2))? {
            Message::Ack => {
                // One-shot servers retain the pipe until this receipt is observed.
                // Closing a Windows server pipe with an unread reply can lose that reply.
                if matches!(message, Message::Activate | Message::Restart(_) | Message::Ready) {
                    self.send(&Message::Ack)?;
                }
                Ok(())
            }
            Message::Cancel => Err(error("起動を中止しました。")),
            _ => Err(error("Unexpected IPC response")),
        }
    }
}

pub fn activate(context: &Context) -> io::Result<()> {
    Connection::connect(&context.endpoint("core"), Duration::from_secs(2))?
        .request(&Message::Activate)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn protocol_rejects_unknown_versions_commands_and_payloads() {
        for bytes in [&[2, 3][..], &[1, 99], &[1, 3, 0], &[1, 2], &[1, 1, b'x'], &[1, 4, 255]] {
            assert!(Message::decode(bytes).is_err());
        }
        for message in [Message::Ready, Message::Phase(Phase::Settings, "翻訳を準備".into()), Message::Hello("a".repeat(64)), Message::Cancel] {
            let bytes = message.encode().unwrap();
            assert_eq!(Message::decode(&bytes[4..]).unwrap(), message);
        }
        assert!(Message::Failed("x".repeat(MAX_FRAME)).encode().is_err());
    }
}
