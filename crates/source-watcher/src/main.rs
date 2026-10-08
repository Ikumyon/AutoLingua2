#![cfg_attr(windows, windows_subsystem = "windows")]

fn main() {
    let mut arguments = std::env::args_os().skip(1);
    if let Some(settings) = arguments.next() {
        if let Err(error) = autolingua2_native::source_watch::run(std::path::Path::new(&settings)) {
            eprintln!("Source watcher: {error}");
        }
    }
}
