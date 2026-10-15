use std::sync::{Arc, Mutex};
use chrono::Local;

#[derive(Clone, Default)]
pub struct ProcessLogger {
    logs: Arc<Mutex<Vec<String>>>,
}

impl ProcessLogger {
    pub fn new() -> Self {
        Self {
            logs: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn log(&self, message: impl AsRef<str>) -> String {
        let now = Local::now().format("%H:%M:%S");
        let line = format!("[{}] {}", now, message.as_ref());
        let mut logs = self.logs.lock().unwrap();
        logs.push(line);
        logs.join("\n")
    }
}
