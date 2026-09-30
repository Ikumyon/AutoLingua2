use super::{error, token, Connection, Context, Listener, Message};
use std::io;
use std::sync::{mpsc, Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

struct Command { message: Message, reply: mpsc::Sender<Result<(), String>> }
#[derive(Default)]
struct State {
    stop: AtomicBool,
    activate: AtomicBool,
    ready: AtomicBool,
    failure: Mutex<Option<String>>,
    restart: Mutex<Option<(String, bool)>>,
}

pub struct Session {
    state: Arc<State>,
    sender: mpsc::Sender<Command>,
    worker: Option<JoinHandle<()>>,
}

impl Session {
    pub fn connect(context: Context, credential: String) -> io::Result<Self> {
        if !super::valid_token(&credential) { return Err(error("Invalid startup credential")); }
        let lock = context.lock("core")?.ok_or_else(|| error("本体は既に起動しています。"))?;
        let mut listener = Listener::bind(&context.endpoint("core"))?;
        let mut startup = Connection::connect(&context.endpoint(&format!("boot-{}", &credential[..16])), Duration::from_secs(2))?;
        startup.request(&Message::Hello(credential))?;
        let state = Arc::new(State::default());
        let shared = state.clone();
        let (sender, receiver) = mpsc::channel::<Command>();
        let worker = thread::spawn(move || {
            let _lock = lock;
            let mut heartbeat = Instant::now();
            let mut pending: Vec<(Connection, Instant, Option<Message>)> = Vec::new();
            let run = (|| -> io::Result<()> {
                while !shared.stop.load(Ordering::Acquire) {
                    while let Ok(command) = receiver.try_recv() {
                        let ready = command.message == Message::Ready;
                        let result = startup.request(&command.message);
                        if ready && result.is_ok() { shared.ready.store(true, Ordering::Release); }
                        let _ = command.reply.send(result.as_ref().map(|_| ()).map_err(ToString::to_string));
                        result?;
                        heartbeat = Instant::now();
                    }
                    if !shared.ready.load(Ordering::Acquire) && heartbeat.elapsed() >= Duration::from_millis(250) {
                        startup.request(&Message::Ping)?;
                        heartbeat = Instant::now();
                    }
                    if pending.len() < 16 {
                        if let Some(stream) = listener.accept()? {
                            pending.push((Connection::new(stream), Instant::now(), None));
                        }
                    }
                    let mut i = 0;
                    while i < pending.len() {
                        let (connection, since, receipt) = &mut pending[i];
                        let remove = match connection.poll() {
                            Ok(Some(Message::Ack)) if receipt.is_some() => {
                                if let Some(Message::Restart(ticket)) = receipt.take() {
                                    let mut restart = shared.restart.lock().map_err(|_| error("Restart state poisoned"))?;
                                    if let Some((expected, accepted)) = restart.as_mut() {
                                        if ticket == *expected { *accepted = true; }
                                    }
                                }
                                true
                            }
                            Ok(Some(Message::Activate)) if receipt.is_none() => {
                                shared.activate.store(true, Ordering::Release);
                                *receipt = Some(Message::Activate);
                                connection.send(&Message::Ack).is_err()
                            }
                            Ok(Some(Message::Restart(ticket))) if receipt.is_none() => {
                                let restart = shared.restart.lock().map_err(|_| error("Restart state poisoned"))?;
                                if let Some((expected, false)) = restart.as_ref() {
                                    if ticket == *expected {
                                        *receipt = Some(Message::Restart(ticket));
                                        connection.send(&Message::Ack).is_err()
                                    } else {
                                        true
                                    }
                                } else { true }
                            }
                            Ok(None) => since.elapsed() > Duration::from_secs(2),
                            _ => true, // Invalid clients cannot bring down the application.
                        };
                        if remove { pending.swap_remove(i); } else { i += 1; }
                    }
                    thread::sleep(Duration::from_millis(10));
                }
                Ok(())
            })();
            if let Err(err) = run {
                if let Ok(mut failure) = shared.failure.lock() { *failure = Some(err.to_string()); }
                #[cfg(feature = "python")]
                if !shared.ready.load(Ordering::Acquire) {
                    crate::platform::abort_startup_plugins();
                    // Python normally notices cancellation at its next phase/timer tick.
                    // Bound uninterruptible third-party imports/discovery after launcher loss.
                    let deadline = Instant::now() + Duration::from_secs(5);
                    while !shared.stop.load(Ordering::Acquire) && Instant::now() < deadline {
                        thread::sleep(Duration::from_millis(25));
                    }
                    if !shared.stop.load(Ordering::Acquire) { std::process::exit(1); }
                }
            }
            drop(listener);
            drop(_lock);
        });
        Ok(Self { state, sender, worker: Some(worker) })
    }

    pub fn check(&self) -> io::Result<()> {
        let failure = self.state.failure.lock().map_err(|_| error("Bootstrap state poisoned"))?;
        match failure.as_ref() {
            Some(message) => Err(error(message.clone())),
            None if self.state.stop.load(Ordering::Acquire) => Err(error("Bootstrap session closed")),
            None => Ok(()),
        }
    }

    pub fn notify(&self, message: Message) -> io::Result<()> {
        self.check()?;
        if self.state.ready.load(Ordering::Acquire) { return Err(error("Startup already completed")); }
        let (reply, result) = mpsc::channel();
        self.sender.send(Command { message, reply }).map_err(error)?;
        result.recv_timeout(Duration::from_secs(4)).map_err(error)?.map_err(error)
    }

    pub fn take_activation(&self) -> bool {
        self.state.ready.load(Ordering::Acquire) && self.state.activate.swap(false, Ordering::AcqRel)
    }

    pub fn prepare_restart(&self) -> io::Result<String> {
        self.check()?;
        if !self.state.ready.load(Ordering::Acquire) { return Err(error("Application is not ready")); }
        let mut restart = self.state.restart.lock().map_err(|_| error("Restart state poisoned"))?;
        if restart.is_some() { return Err(error("Restart already pending")); }
        let ticket = token()?;
        *restart = Some((ticket.clone(), false));
        Ok(ticket)
    }

    pub fn wait_restart(&self, timeout: Duration) -> io::Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            self.check()?;
            {
                let mut restart = self.state.restart.lock().map_err(|_| error("Restart state poisoned"))?;
                match restart.as_ref() {
                    Some((_, true)) => return Ok(()),
                    None => return Err(error("Restart cancelled")),
                    _ if Instant::now() >= deadline => {
                        *restart = None;
                        return Err(error("ランチャーへの再起動引き継ぎがタイムアウトしました。"));
                    }
                    _ => (),
                }
            }
            thread::sleep(Duration::from_millis(10));
        }
    }

    pub fn cancel_restart(&self) {
        if let Ok(mut restart) = self.state.restart.lock() { *restart = None; }
    }

    pub fn close(&mut self) {
        self.state.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() { let _ = worker.join(); }
    }
}
impl Drop for Session { fn drop(&mut self) { self.close(); } }
