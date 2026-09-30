use super::{error, os, Phase};
use std::io;

pub const MAX_FRAME: usize = 16 * 1024;

pub fn token() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    os::random(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

pub fn valid_token(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_hexdigit())
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

    pub(super) fn decode(data: &[u8]) -> io::Result<Self> {
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
