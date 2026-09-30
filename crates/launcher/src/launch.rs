use crate::{lifecycle::StartupClock, SplashWindow};
use autolingua2_native::bootstrap::{self, error, Connection, Context, Listener, Message, StartupProgress};
use autolingua2_native::platform;
use std::ffi::OsString;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

pub struct Ui(slint::Weak<SplashWindow>);
impl Ui {
    pub fn new(weak: slint::Weak<SplashWindow>) -> Self { Self(weak) }
    fn update(&self, action: impl FnOnce(SplashWindow) + Send + 'static) {
        let weak = self.0.clone();
        let _ = slint::invoke_from_event_loop(move || { if let Some(window) = weak.upgrade() { action(window); } });
    }
    pub fn phase(&self, text: String) {
        self.update(move |window| { window.set_status_text(text.into()); window.set_delayed(false); });
    }
    pub fn progress(&self, value: f32) {
        self.update(move |window| window.set_progress(value));
    }
    pub fn delay(&self, delayed: bool, owned: bool) {
        self.update(move |window| { window.set_delayed(delayed); window.set_can_cancel(owned); });
    }
    pub fn fail(&self, message: String) {
        self.update(move |window| {
            window.set_failed(true);
            window.set_delayed(false);
            window.set_status_text("AUTOlingua2 を起動できませんでした".into());
            window.set_detail(message.into());
        });
    }
}

struct Target { executable: PathBuf, args: Vec<OsString>, root: PathBuf, development: Option<PathBuf> }
impl Target {
    fn resolve() -> io::Result<Self> {
        let mut args = std::env::args_os().skip(1);
        let mut forwarded = Vec::new();
        let mut development = None;
        while let Some(arg) = args.next() {
            if arg == "--development-root" {
                if development.is_some() { return Err(error("Duplicate development root")); }
                development = Some(PathBuf::from(args.next().ok_or_else(|| error("Missing development root"))?).canonicalize()?);
            } else { forwarded.push(arg); }
        }
        let (root, executable, mut arguments) = if let Some(root) = &development {
            let python = root.join(platform::development_python());
            (root.clone(), python, vec![root.join("main.py").into_os_string()])
        } else {
            let exe = std::env::current_exe()?;
            let root = exe.parent().ok_or_else(|| error("Launcher directory unavailable"))?.to_path_buf();
            let core = root.join(platform::executable_name("autolingua2_core"));
            (root, core, vec![])
        };
        if !executable.is_file() { return Err(error(format!("実行対象がありません: {}", executable.display()))); }
        arguments.extend(forwarded);
        Ok(Self { executable, args: arguments, root, development })
    }

    fn spawn(&self, credential: &str) -> io::Result<Child> {
        let mut command = Command::new(&self.executable);
        command.args(&self.args).current_dir(&self.root)
            .env("AUTOLINGUA_BOOT_TOKEN", credential)
            .env("AUTOLINGUA_LAUNCHER", std::env::current_exe()?)
            .env_remove("AUTOLINGUA_RESTART_TICKET").env_remove("AUTOLINGUA_RESTART_PID")
            .env("PYINSTALLER_RESET_ENVIRONMENT", "1")
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::from(log_file()?));
        if let Some(root) = &self.development {
            command.env("AUTOLINGUA_DEVELOPMENT_ROOT", root);
            command.env("PYTHONPATH", std::env::join_paths([root.join("build/native"), root.join("src")]).map_err(error)?);
        } else { command.env_remove("AUTOLINGUA_DEVELOPMENT_ROOT"); }
        platform::configure_core_command(&mut command);
        command.spawn().map_err(|err| error(format!("本体プロセスの生成に失敗しました: {err}")))
    }
}

pub fn log_directory() -> io::Result<PathBuf> {
    platform::log_directory()
}
fn log_file() -> io::Result<std::fs::File> {
    let directory = log_directory()?;
    std::fs::create_dir_all(&directory)?;
    OpenOptions::new().create(true).append(true).open(directory.join("launcher.log"))
}
pub fn record_failure(message: &str) {
    if let Ok(mut log) = log_file() { let _ = writeln!(log, "{:?} {message}", SystemTime::now()); }
}
pub fn open_logs() -> io::Result<()> {
    let path = log_directory()?;
    std::fs::create_dir_all(&path)?;
    platform::open_folder(&path)
}

pub fn run(ui: &Ui, cancel: &AtomicBool) -> io::Result<()> {
    let target = Target::resolve()?;
    let context = Context::new(target.development.as_deref())?;
    let restart = std::env::var("AUTOLINGUA_RESTART_TICKET").ok();
    let start = Instant::now();
    let _startup_lock = loop {
        if cancel.load(Ordering::Acquire) { return Ok(()); }
        if let Some(lock) = context.lock("startup")? { break lock; }
        if restart.is_none() && context.core_running()? {
            return bootstrap::activate(&context).map_err(|err| error(format!("既存の本体が応答しません: {err}")));
        }
        if restart.is_some() && start.elapsed() > Duration::from_secs(4) {
            return Err(error("別の起動処理が進行中のため再起動を引き継げません。"));
        }
        ui.delay(start.elapsed() >= Duration::from_secs(60), false);
        thread::sleep(Duration::from_millis(25));
    };
    if let Some(ticket) = restart {
        if !bootstrap::valid_token(&ticket) { return Err(error("Invalid restart ticket")); }
        let pid: u32 = std::env::var("AUTOLINGUA_RESTART_PID").map_err(error)?.parse().map_err(error)?;
        let old_process = bootstrap::ProcessWatch::open(pid)?;
        let mut connection = Connection::connect(&context.endpoint("core"), Duration::from_secs(2))?;
        connection.request(&Message::Restart(ticket))?;
        ui.phase("旧本体の終了を待っています…".into());
        let deadline = Instant::now() + Duration::from_secs(30);
        while old_process.alive()? || context.core_running()? {
            if Instant::now() >= deadline { return Err(error("旧本体が終了しなかったため、再起動を中止しました。")); }
            thread::sleep(Duration::from_millis(25));
        }
    } else if context.core_running()? {
        return bootstrap::activate(&context).map_err(|err| error(format!("既存の本体が応答しません: {err}")));
    }
    let _ = bootstrap::update_status();
    let credential = bootstrap::token()?;
    let mut listener = Listener::bind(&context.endpoint(&format!("boot-{}", &credential[..16])))?;
    let mut child = target.spawn(&credential)?;
    ui.phase("本体の初期化を待っています…".into());
    let result = monitor(ui, cancel, &mut child, &mut listener, &credential);
    if result.is_err() {
        // Dropping the bootstrap connection tells the core to stop and clean up plugins.
        let deadline = Instant::now() + Duration::from_secs(5);
        while child.try_wait()?.is_none() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(25));
        }
        if child.try_wait()?.is_none() { child.kill()?; }
        child.wait()?;
    }
    result
}

fn monitor(ui: &Ui, cancel: &AtomicBool, child: &mut Child, listener: &mut Listener, credential: &str) -> io::Result<()> {
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
                                let text = phase.clone();
                                ui.update(move |window| window.set_status_text(text.into()));
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
