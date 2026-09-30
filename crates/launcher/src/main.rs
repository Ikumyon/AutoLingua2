#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod lifecycle;
mod launch;
slint::include_modules!();
use slint::ComponentHandle;
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let splash = SplashWindow::new()?;
    let cancel = Arc::new(AtomicBool::new(false));
    let cancel_clicked = cancel.clone();
    splash.on_cancel(move || { cancel_clicked.store(true, Ordering::Release); });
    splash.on_dismiss(|| { let _ = slint::quit_event_loop(); });
    let weak = splash.as_weak();
    splash.on_open_logs(move || {
        if let Err(err) = launch::open_logs() {
            if let Some(splash) = weak.upgrade() {
                splash.set_detail(format!("ログフォルダを開けませんでした: {err}").into());
            }
        }
    });
    let close_cancel = cancel.clone();
    let weak = splash.as_weak();
    splash.window().on_close_requested(move || {
        if weak.upgrade().is_some_and(|window| window.get_failed()) {
            slint::CloseRequestResponse::HideWindow
        } else {
            close_cancel.store(true, Ordering::Release);
            slint::CloseRequestResponse::KeepWindowShown
        }
    });
    splash.show()?;
    let weak = splash.as_weak();
    let start = slint::Timer::default();
    start.start(slint::TimerMode::SingleShot, Duration::from_millis(1), move || {
        let weak = weak.clone();
        let cancel = cancel.clone();
        std::thread::spawn(move || {
            let ui = launch::Ui::new(weak);
            match launch::run(&ui, &cancel) {
                Ok(()) => { let _ = slint::invoke_from_event_loop(|| { let _ = slint::quit_event_loop(); }); }
                Err(err) => { launch::record_failure(&err.to_string()); ui.fail(err.to_string()); }
            }
        });
    });
    slint::run_event_loop()?;
    Ok(())
}
