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

fn parse_version(v: &str) -> Option<(u64, u64, u64)> {
    let s = v.trim().trim_start_matches(|c| c == 'v' || c == 'V');
    let mut parts = s.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    let patch = parts.next().and_then(|p| p.split('-').next()).and_then(|p| p.parse().ok()).unwrap_or(0);
    Some((major, minor, patch))
}

fn format_json(state: &str, current: &str, latest: &str, url: &str, notes: &str, message: &str) -> String {
    serde_json::json!({
        "state": state,
        "current_version": current,
        "latest_version": latest,
        "download_url": url,
        "release_notes": notes,
        "message": message,
    }).to_string()
}

pub fn update_status() -> String {
    let current_version = env!("CARGO_PKG_VERSION");
    let test_url = std::env::var("AUTOLINGUA_UPDATE_TEST_URL").ok();
    let url = test_url.as_deref().unwrap_or("https://api.github.com/repos/Ikumyon/AutoLingua2/releases/latest");

    let mut command = std::process::Command::new("curl");
    os::configure_core_command(&mut command);
    let output = command.args([
            "-s",
            "--max-time", "5",
            "-H", "User-Agent: AUTOlingua2",
            "-H", "Accept: application/vnd.github.v3+json",
            url,
        ])
        .output();

    let output = match output {
        Ok(out) if out.status.success() => out,
        Ok(_) => return format_json("unavailable", current_version, "", "", "", "更新情報の取得に失敗しました。"),
        Err(_) => return format_json("unavailable", current_version, "", "", "", "更新確認ツール (curl) の実行に失敗しました。"),
    };

    let text = match String::from_utf8(output.stdout) {
        Ok(t) => t,
        Err(_) => return format_json("unavailable", current_version, "", "", "", "応答データのデコードに失敗しました。"),
    };

    let Ok(json): Result<serde_json::Value, _> = serde_json::from_str(&text) else {
        return format_json("unavailable", current_version, "", "", "", "応答JSONの解析に失敗しました。");
    };

    let Some(tag_name) = json.get("tag_name").and_then(|v| v.as_str()) else {
        return format_json("unavailable", current_version, "", "", "", "リリース情報が見つかりませんでした。");
    };

    let latest_version = tag_name.trim_start_matches(|c| c == 'v' || c == 'V');
    let release_notes = json.get("body").and_then(|v| v.as_str()).unwrap_or("");

    let mut download_url = "";
    if let Some(assets) = json.get("assets").and_then(|v| v.as_array()) {
        for asset in assets {
            if let Some(name) = asset.get("name").and_then(|v| v.as_str()) {
                if name.ends_with(".zip") {
                    if let Some(url) = asset.get("browser_download_url").and_then(|v| v.as_str()) {
                        download_url = url;
                        break;
                    }
                }
            }
        }
    }

    let is_newer = match (parse_version(current_version), parse_version(latest_version)) {
        (Some(curr), Some(latest)) => latest > curr || (test_url.is_some() && latest == curr),
        _ => false,
    };

    if is_newer {
        format_json(
            "available",
            current_version,
            latest_version,
            download_url,
            release_notes,
            &format!("新しいバージョン v{} が利用可能です。", latest_version),
        )
    } else {
        format_json(
            "up_to_date",
            current_version,
            latest_version,
            download_url,
            release_notes,
            &format!("お使いのバージョン (v{}) は最新です。", current_version),
        )
    }
}

pub fn error(message: impl std::fmt::Display) -> io::Error {
    io::Error::other(message.to_string())
}
