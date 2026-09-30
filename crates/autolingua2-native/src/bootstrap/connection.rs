use super::{error, Context, Message, Stream, MAX_FRAME};
use std::io::{self, Read, Write};
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

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
