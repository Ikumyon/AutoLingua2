//! The only process boundary protocol. No application/domain operations belong here.
use std::io;

use crate::platform::os_impl as os;
pub use os::{Listener, ProcessWatch, Stream};

mod connection;
mod context;
mod progress;
mod protocol;
pub mod core;
#[cfg(test)]
mod integration_tests;
#[cfg(feature = "python")]
pub mod bindings;

pub use connection::{activate, Connection};
pub use context::{Context, InstanceLock};
pub use progress::{Phase, StartupProgress};
pub use protocol::{token, valid_token, Message, MAX_FRAME};

pub fn error(message: impl std::fmt::Display) -> io::Error {
    io::Error::other(message.to_string())
}
