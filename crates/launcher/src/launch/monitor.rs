use super::lifecycle::StartupClock;
use crate::ui::Ui;
use autolingua2_native::bootstrap::{error, Connection, Listener, Message, StartupProgress};
use std::io;
use std::process::Child;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

pub(super) fn monitor(ui: &Ui, cancel: &AtomicBool, child: &mut Child, listener: &mut Listener, credential: &str) -> io::Result<()> {
    let start = Instant::now();
    let mut clock = StartupClock::new();
    let mut connection: Option<Connection> = None;
    let mut authenticated = false;
    let mut connected_at = Instant::now();
    let mut phase = "本体プロセスの起動".to_string();
    let mut failure: Option<String> = None;
    let mut ready_sent = false;
    let mut progress = StartupProgress::default();
    loop {
        let elapsed = start.elapsed();
        if cancel.load(Ordering::Acquire) && !clock.cancelling() {
            clock.cancel(elapsed);
            ui.phase("起動を中止しています…".into());
        }
        if let Some(status) = child.try_wait()? {
            return Err(error(failure.unwrap_or_else(|| format!("{phase}: READY前に本体が終了しました ({status})"))));
        }
        if clock.must_kill(elapsed) {
            child.kill()?;
            child.wait()?;
            return Err(error(failure.unwrap_or_else(|| format!("{phase}: 起動を中止しました。"))));
        }
        ui.delay(clock.delayed(elapsed), true);
        if connection.is_none() {
            if let Some(stream) = listener.accept()? {
                connection = Some(Connection::new(stream));
                connected_at = Instant::now();
            }
        }
        if let Some(channel) = connection.as_mut() {
            match channel.poll() {
                Ok(Some(Message::Hello(value))) if !authenticated && value == credential => {
                    authenticated = true;
                    channel.send(if clock.cancelling() { &Message::Cancel } else { &Message::Ack })?;
                }
                Ok(Some(message)) if authenticated => {
                    if clock.cancelling() {
                        channel.send(&Message::Cancel)?;
                    } else {
                        match message {
                            Message::Ack if ready_sent => {
                                ui.progress(progress.finish()?);
                                return Ok(());
                            }
                            Message::Phase(id, value) if !ready_sent => {
                                if progress.advance(id)? { clock.progress(elapsed); }
                                phase = value;
                                ui.progress(id.progress());
                                // Repeated notifications must not clear an existing delay notice.
                                ui.status(phase.clone());
                                ui.delay(clock.delayed(elapsed), true);
                                channel.send(&Message::Ack)?;
                            }
                            Message::Ping => channel.send(&Message::Ack)?,
                            Message::Ready if !ready_sent => {
                                progress.finish()?;
                                channel.send(&Message::Ack)?;
                                ready_sent = true;
                            }
                            Message::Failed(value) => {
                                failure = Some(format!("{phase}: {value}"));
                                clock.cancel(elapsed);
                                channel.send(&Message::Ack)?;
                            }
                            _ => return Err(error(format!("{phase}: 不正な起動通知を受信しました。"))),
                        }
                    }
                }
                Ok(None) if authenticated || connected_at.elapsed() < Duration::from_secs(2) => (),
                Err(err) if authenticated => {
                    if failure.is_none() { failure = Some(format!("{phase}: 起動通信が切断されました: {err}")); }
                    clock.cancel(elapsed);
                    connection = None;
                    authenticated = false;
                }
                _ => { connection = None; authenticated = false; }
            }
        }
        thread::sleep(Duration::from_millis(20));
    }
}
