//! Headless source monitoring. Only this boundary touches native lifecycle APIs.
mod os;
pub mod notification;
#[cfg(feature = "python")]
pub mod bindings;

use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::hash::Hasher;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

type Hashes = BTreeMap<String, String>;

fn invalid(message: &str) -> io::Error { io::Error::new(io::ErrorKind::InvalidData, message) }

fn directory(settings: &Path) -> PathBuf { settings.with_extension("watch") }

fn lock(path: &Path) -> io::Result<File> {
    fs::create_dir_all(path.parent().ok_or_else(|| invalid("Missing lock parent"))?)?;
    OpenOptions::new().read(true).write(true).create(true).truncate(false).open(path)
}

fn read_json(path: &Path) -> io::Result<Value> {
    match fs::read(path) {
        Ok(data) => serde_json::from_slice(&data).map_err(io::Error::other),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(json!({})),
        Err(error) => Err(error),
    }
}

fn write_json(path: &Path, value: &Value) -> io::Result<()> {
    let temporary = path.with_extension("tmp");
    let mut file = File::create(&temporary)?;
    file.write_all(&serde_json::to_vec(value).map_err(io::Error::other)?)?;
    file.sync_all()?;
    drop(file);
    os::replace(&temporary, path)
}

fn configuration(settings: &Path) -> io::Result<Value> {
    let guard = lock(&directory(settings).join("configuration.lock"))?;
    guard.lock()?;
    let path = directory(settings).join("targets.json");
    if path.exists() { return read_json(&path); }
    let data = read_json(settings)?;
    let mut config = data.get("source_watch").cloned().unwrap_or_else(|| json!({"enabled":false,"targets":[]}));
    if let Some(profiles) = config.get("notifications").and_then(Value::as_array).cloned() {
        if let Some(list) = config.get_mut("targets").and_then(Value::as_array_mut) {
            list.retain_mut(|target| {
                if let Some(profile) = profiles.iter().find(|entry| entry.get("project_path") == target.get("project_path")) {
                    target["icon_path"] = profile.get("icon_path").cloned().unwrap_or(json!(""));
                    target["sound_path"] = profile.get("sound_path").cloned().unwrap_or(json!(""));
                    true
                } else { false }
            });
        }
    }
    if let Some(object) = config.as_object_mut() { object.remove("notifications"); }
    write_json(&path, &config)?;
    Ok(config)
}

pub fn target_settings(settings: &Path) -> io::Result<String> { Ok(configuration(settings)?.to_string()) }

pub fn save_target_settings(settings: &Path, data: &str) -> io::Result<()> {
    let config: Value = serde_json::from_str(data).map_err(io::Error::other)?;
    if config.get("enabled").and_then(Value::as_bool).is_none() { return Err(invalid("Invalid watcher state")); }
    let mut roots = std::collections::BTreeSet::new();
    for target in targets(&config)? {
        let root = string(target, "source_root")?;
        if !Path::new(root).is_absolute() || !roots.insert(root) { return Err(invalid("Invalid or duplicate source path")); }
        if target.get("suffixes").and_then(Value::as_array).is_none() { return Err(invalid("Missing parser suffixes")); }
    }
    let guard = lock(&directory(settings).join("configuration.lock"))?;
    guard.lock()?;
    write_json(&directory(settings).join("targets.json"), &config)
}

fn targets(config: &Value) -> io::Result<&Vec<Value>> {
    config.get("targets").and_then(Value::as_array).ok_or_else(|| invalid("Invalid watch targets"))
}

fn same_source(left: &Value, right: &Value) -> bool {
    ["source_root", "suffixes"].iter().all(|key| left.get(key) == right.get(key))
}

fn string<'a>(target: &'a Value, key: &str) -> io::Result<&'a str> {
    target.get(key).and_then(Value::as_str).filter(|s| !s.is_empty())
        .ok_or_else(|| invalid("Invalid watch target"))
}

fn cancellation<'a>(settings: Option<&'a Path>, target: Option<&'a Value>) -> impl FnMut() -> io::Result<()> + 'a {
    let mut last_check = Instant::now() - Duration::from_secs(1);
    move || {
        if let Some(settings) = settings {
            if last_check.elapsed() >= Duration::from_millis(100) {
                last_check = Instant::now();
                let config = configuration(settings)?;
                if config.get("enabled").and_then(Value::as_bool) != Some(true) {
                    return Err(io::Error::new(io::ErrorKind::Interrupted, "Source watcher disabled"));
                }
                if let Some(target) = target {
                    if !targets(&config)?.iter().any(|entry| same_source(entry, target)) {
                        return Err(io::Error::new(io::ErrorKind::Interrupted, "Watch target removed or changed"));
                    }
                }
            }
        }
        Ok(())
    }
}

fn scan(target: &Value, settings: Option<&Path>) -> io::Result<Hashes> {
    let mut check_cancelled = cancellation(settings, Some(target));
    let root = Path::new(string(target, "source_root")?);
    if !root.is_absolute() || !root.is_dir() { return Err(invalid("Source folder is unavailable")); }
    let suffixes = target.get("suffixes").and_then(Value::as_array)
        .ok_or_else(|| invalid("Missing parser suffixes"))?;
    let mut directories = vec![root.to_path_buf()];
    let mut hashes = Hashes::new();
    while let Some(directory) = directories.pop() {
        check_cancelled()?;
        for entry in fs::read_dir(directory)? {
            check_cancelled()?;
            let entry = entry?;
            let kind = entry.file_type()?;
            // Symlinks are outside the registered source tree's ownership.
            if kind.is_symlink() { continue; }
            if kind.is_dir() { directories.push(entry.path()); continue; }
            if !kind.is_file() { continue; }
            let path = entry.path();
            let extension = path.extension().and_then(|s| s.to_str()).unwrap_or("");
            if !suffixes.iter().any(|s| s.as_str().is_some_and(|s| s.eq_ignore_ascii_case(&format!(".{extension}")))) {
                continue;
            }
            let mut input = File::open(&path)?;
            let before = input.metadata()?;
            let mut hash = std::collections::hash_map::DefaultHasher::new();
            let mut buffer = [0u8; 65536];
            loop {
                check_cancelled()?;
                let count = input.read(&mut buffer)?;
                if count == 0 { break; }
                hash.write(&buffer[..count]);
            }
            let after = input.metadata()?;
            let current = fs::metadata(&path)?;
            if before.len() != after.len() || before.modified()? != after.modified()?
                || after.len() != current.len() || after.modified()? != current.modified()? {
                return Err(invalid("Source file changed during scan"));
            }
            let relative = path.strip_prefix(root).map_err(io::Error::other)?
                .to_str().ok_or_else(|| invalid("Non-Unicode source path"))?.replace('\\', "/");
            hashes.insert(relative, format!("{:016x}", hash.finish()));
        }
    }
    Ok(hashes)
}

fn with_state<T>(settings: &Path, action: impl FnOnce(&mut Value) -> io::Result<T>) -> io::Result<T> {
    let directory = directory(settings);
    let guard = lock(&directory.join("state.lock"))?;
    guard.lock()?;
    let path = directory.join("state.json");
    let mut state = read_json(&path)?;
    let before = state.clone();
    if let Some(entries) = state.as_object_mut() {
        let moves: Vec<_> = entries.iter().filter_map(|(key, entry)| {
            entry.get("target").and_then(|target| target.get("source_root")).and_then(Value::as_str)
                .filter(|root| *root != key.as_str()).map(|root| (key.clone(), root.to_owned()))
        }).collect();
        for (old, root) in moves {
            if let Some(entry) = entries.remove(&old) { entries.entry(root).or_insert(entry); }
        }
    }
    let result = action(&mut state)?;
    if state != before { write_json(&path, &state)?; }
    Ok(result)
}

pub fn running(settings: &Path) -> io::Result<bool> {
    let guard = lock(&directory(settings).join("daemon.lock"))?;
    match guard.try_lock() {
        Ok(()) => Ok(false),
        Err(std::fs::TryLockError::WouldBlock) => Ok(true),
        Err(std::fs::TryLockError::Error(error)) => Err(error),
    }
}

pub fn configure(settings: &Path, executable: &Path, enabled: bool, launcher: &[String], icon: &str) -> io::Result<()> {
    if enabled {
        if !executable.is_file() { return Err(io::Error::new(io::ErrorKind::NotFound, "Source watcher executable is missing; build the Rust components")); }
        notification::setup(launcher, icon)?;
        os::autostart(settings, executable, true)?;
        if !running(settings)? {
            let mut command = Command::new(executable);
            command.arg(settings).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
            os::detach(&mut command);
            let mut child = command.spawn()?;
            std::thread::spawn(move || { let _ = child.wait(); });
        }
    } else {
        os::autostart(settings, executable, false)?;
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    while running(settings)? != enabled {
        if Instant::now() >= deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "Source watcher did not reach requested state")); }
        std::thread::sleep(Duration::from_millis(50));
    }
    Ok(())
}

pub fn snapshot(settings: &Path, project: &str) -> io::Result<String> {
    let config = configuration(settings)?;
    let target = targets(&config)?.iter().find(|t| t.get("source_root").and_then(Value::as_str) == Some(project))
        .ok_or_else(|| invalid("Project is not registered for monitoring"))?;
    let hashes = scan(target, None)?;
    Ok(json!({"target":target,"hashes":hashes}).to_string())
}

pub fn acknowledge(settings: &Path, project: &str, snapshot: &str) -> io::Result<()> {
    let snapshot: Value = serde_json::from_str(snapshot).map_err(io::Error::other)?;
    with_state(settings, |state| {
        let entry = state.get_mut(project).ok_or_else(|| invalid("Missing watch baseline"))?;
        if !entry.get("target").zip(snapshot.get("target")).is_some_and(|(left, right)| same_source(left, right)) {
            return Err(invalid("Watch target changed"));
        }
        entry["baseline"] = snapshot.get("hashes").cloned().ok_or_else(|| invalid("Missing hashes"))?;
        Ok(())
    })
}

pub fn status(settings: &Path) -> io::Result<String> {
    let guard = lock(&directory(settings).join("state.lock"))?;
    guard.lock_shared()?;
    Ok(read_json(&directory(settings).join("state.json"))?.to_string())
}

pub fn forget_target(settings: &Path, project: &str) -> io::Result<()> {
    with_state(settings, |state| {
        let entries = state.as_object_mut().ok_or_else(|| invalid("Invalid watcher state"))?;
        entries.remove(project);
        Ok(())
    })
}

fn check(settings: &Path, config: &Value) -> io::Result<()> {
    for target in targets(config)? {
        if configuration(settings)?.get("enabled").and_then(Value::as_bool) != Some(true) { break; }
        let project = string(target, "source_root")?;
        let result = scan(target, Some(settings));
        with_state(settings, |state| {
            let latest = configuration(settings)?;
            if !targets(&latest)?.iter().any(|entry| same_source(entry, target)) { return Ok(()); }
            if !state.get(project).and_then(|s| s.get("target")).is_some_and(|old| same_source(old, target)) {
                if let Ok(ref hashes) = result {
                    state[project] = json!({"target":target,"baseline":hashes,"current":hashes,"error":""});
                } else {
                    state[project] = json!({"target":target,"error":result.as_ref().err().map(ToString::to_string)});
                }
            } else {
                let entry = &mut state[project];
                entry["target"] = target.clone();
                match &result {
                    Ok(hashes) => {
                        if entry.get("baseline").is_none() { entry["baseline"] = json!(hashes); }
                        entry["current"] = json!(hashes);
                        entry["error"] = json!("");
                    }
                    Err(error) => entry["error"] = json!(error.to_string()),
                }
            }
            Ok(())
        })?;
    }
    with_state(settings, |state| {
        let latest = configuration(settings)?;
        let object = state.as_object_mut().ok_or_else(|| invalid("Invalid watcher state"))?;
        object.retain(|project, _| targets(&latest).is_ok_and(|targets| targets.iter().any(|t| t.get("source_root").and_then(Value::as_str) == Some(project))));
        Ok(())
    })?;
    notify_updates(settings)
}

fn notify_updates(settings: &Path) -> io::Result<()> {
    let config = configuration(settings)?;
    let entries = targets(&config)?.clone();
    let cached: Value = serde_json::from_str(&status(settings)?).map_err(io::Error::other)?;
    for entry in &entries {
        let project = string(entry, "source_root")?;
        let Some(state) = cached.get(project) else { continue; };
        let Some(current) = state.get("current").and_then(Value::as_object) else { continue; };
        let Some(baseline) = state.get("baseline").and_then(Value::as_object) else { continue; };
        if state.get("error").and_then(Value::as_str).is_some_and(|error| !error.is_empty())
            || current == baseline || state.get("notified") == state.get("current") { continue; }
        let latest = configuration(settings)?;
        if latest.get("enabled").and_then(Value::as_bool) != Some(true)
            || !targets(&latest)?.contains(entry) { continue; }
        if !state.get("target").is_some_and(|target| same_source(target, entry)) { continue; }
        let added = current.keys().filter(|key| !baseline.contains_key(*key)).count();
        let modified = current.iter().filter(|(key, value)| baseline.get(*key).is_some_and(|old| old != *value)).count();
        let deleted = baseline.keys().filter(|key| !current.contains_key(*key)).count();
        let name = state.get("target").and_then(|target| target.get("name")).and_then(Value::as_str).unwrap_or(project);
        let result = notification::show(project, name,
            &format!("翻訳元が更新されました。追加: {added} / 変更: {modified} / 削除: {deleted}"),
            entry.get("icon_path").and_then(Value::as_str).unwrap_or(""),
            entry.get("sound_path").and_then(Value::as_str).unwrap_or(""));
        with_state(settings, |state| {
            if let Some(target) = state.get_mut(project) {
                match &result {
                    Ok(()) => { target["notified"] = json!(current); target["notification_error"] = json!(""); }
                    Err(error) => target["notification_error"] = json!(error.to_string()),
                }
            }
            Ok(())
        })?;
    }
    Ok(())
}

pub fn run(settings: &Path) -> io::Result<()> {
    let guard = lock(&directory(settings).join("daemon.lock"))?;
    match guard.try_lock() {
        Ok(()) => (),
        Err(std::fs::TryLockError::WouldBlock) => return Ok(()),
        Err(std::fs::TryLockError::Error(error)) => return Err(error),
    }
    let mut previous = Value::Null;
    let mut notifications = Vec::new();
    let mut last_scan = Instant::now() - Duration::from_secs(300);
    let mut dirty_since = None;
    loop {
        let config = configuration(settings)?;
        if config.get("enabled").and_then(Value::as_bool) != Some(true) { return Ok(()); }
        if config != previous || last_scan.elapsed() >= Duration::from_secs(300) {
            notifications.clear();
            let mut check_cancelled = cancellation(Some(settings), None);
            for target in targets(&config)? {
                if let Ok(notification) = os::Notification::new(Path::new(string(target, "source_root")?), &mut check_cancelled) {
                    notifications.push(notification);
                }
            }
            check(settings, &config)?;
            last_scan = Instant::now();
            dirty_since = None;
            previous = config;
        }
        for notification in &mut notifications {
            match notification.changed() {
                Ok(true) => dirty_since = Some(Instant::now()),
                Ok(false) => (),
                Err(_) => previous = Value::Null,
            }
        }
        if dirty_since.is_some_and(|since| since.elapsed() >= Duration::from_secs(2)) {
            // Re-register native watches to include new folders or replaced trees.
            previous = Value::Null;
        }
        std::thread::sleep(Duration::from_secs(1));
    }
}
