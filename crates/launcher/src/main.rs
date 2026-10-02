#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod launch;
mod logging;
mod ui;
slint::include_modules!();
use slint::ComponentHandle;
use std::path::{Path, PathBuf};
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn find_splash_folder() -> Option<PathBuf> {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let candidate = parent.join("splash");
            if candidate.is_dir() {
                return Some(candidate);
            }
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        let candidate = cwd.join("splash");
        if candidate.is_dir() {
            return Some(candidate);
        }
    }
    None
}

fn pick_random_splash_image(dir: &Path) -> Option<PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    let supported_exts = ["png", "jpg", "jpeg", "webp", "bmp"];
    let mut images = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() {
            if let Some(ext) = path.extension().and_then(|s| s.to_str()) {
                if supported_exts.iter().any(|&e| e.eq_ignore_ascii_case(ext)) {
                    images.push(path);
                }
            }
        }
    }
    if images.is_empty() {
        return None;
    }
    let ticks = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| (d.as_nanos() / 100) as usize)
        .unwrap_or(0);
    let pid = std::process::id() as usize;
    let mut x = ticks ^ pid.rotate_left(16);
    x ^= x >> 30;
    x = x.wrapping_mul(0xbf58476d1ce4e5b9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94d049bb133111eb);
    x ^= x >> 31;
    let index = x % images.len();
    Some(images.swap_remove(index))
}

fn apply_splash_image(splash: &SplashWindow) {
    let Some(folder) = find_splash_folder() else { return; };
    let Some(image_path) = pick_random_splash_image(&folder) else { return; };
    let Ok(image) = slint::Image::load_from_path(&image_path) else { return; };

    let size = image.size();
    let img_w = size.width as f32;
    let img_h = size.height as f32;

    if img_w <= 0.0 || img_h <= 0.0 {
        return;
    }

    let min_w = 480.0;
    let min_h = 260.0;
    let max_w = 900.0;
    let max_h = 650.0;

    let mut target_w = img_w;
    let mut target_h = img_h;

    // 画面からはみ出さないようにスケールダウン
    let scale_down = (max_w / target_w).min(max_h / target_h).min(1.0);
    target_w *= scale_down;
    target_h *= scale_down;

    // 最小サイズを下回る場合はスケールアップ
    let scale_up = (min_w / target_w).max(min_h / target_h).max(1.0);
    target_w *= scale_up;
    target_h *= scale_up;

    // クランプガード
    target_w = target_w.clamp(min_w, max_w);
    target_h = target_h.clamp(min_h, max_h);

    splash.set_custom_image(image);
    splash.set_has_custom_image(true);
    splash.set_window_width(target_w);
    splash.set_window_height(target_h);
    splash.window().set_size(slint::LogicalSize::new(target_w, target_h));
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let splash = SplashWindow::new()?;
    apply_splash_image(&splash);
    let cancel = Arc::new(AtomicBool::new(false));
    let cancel_clicked = cancel.clone();
    splash.on_cancel(move || { cancel_clicked.store(true, Ordering::Release); });
    splash.on_dismiss(|| { let _ = slint::quit_event_loop(); });
    let weak = splash.as_weak();
    splash.on_open_logs(move || {
        if let Err(err) = logging::open_logs() {
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
            let ui = ui::Ui::new(weak);
            match launch::run(&ui, &cancel) {
                Ok(()) => { let _ = slint::invoke_from_event_loop(|| { let _ = slint::quit_event_loop(); }); }
                Err(err) => { logging::record_failure(&err.to_string()); ui.fail(err.to_string()); }
            }
        });
    });
    slint::run_event_loop()?;
    Ok(())
}
