mod lifecycle;
mod monitor;
mod target;

use crate::ui::Ui;
use self::{monitor::monitor, target::Target};
use autolingua2_native::bootstrap::{self, error, Connection, Context, Listener, Message};
use std::io;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

pub fn run(ui: &Ui, cancel: &AtomicBool) -> io::Result<()> {
    let target = Target::resolve()?;
    let context = Context::new(target.development.as_deref())?;
    let restart = std::env::var("AUTOLINGUA_RESTART_TICKET").ok();
    let start = Instant::now();
    let _startup_lock = loop {
        if cancel.load(Ordering::Acquire) { return Ok(()); }
        if let Some(lock) = context.lock("startup")? { break lock; }
        if restart.is_none() && context.core_running()? {
            return target.activate(&context).map_err(|err| error(format!("既存の本体が応答しません: {err}")));
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
        return target.activate(&context).map_err(|err| error(format!("既存の本体が応答しません: {err}")));
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
