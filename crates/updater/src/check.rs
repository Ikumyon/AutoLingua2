use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateInfo {
    pub has_update: bool,
    pub current_version: String,
    pub latest_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub published_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub download_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub download_size: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sha256: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub release_notes: Option<String>,
}

#[derive(Deserialize)]
struct GitHubRelease {
    tag_name: String,
    published_at: Option<String>,
    body: Option<String>,
    assets: Vec<GitHubAsset>,
}

#[derive(Deserialize)]
struct GitHubAsset {
    name: String,
    browser_download_url: String,
    size: u64,
}

pub fn normalize_version(ver: &str) -> &str {
    ver.trim().trim_start_matches('v')
}

pub fn parse_version_numbers(ver: &str) -> Vec<u64> {
    normalize_version(ver)
        .split('.')
        .filter_map(|part| part.split('-').next().unwrap_or("").parse::<u64>().ok())
        .collect()
}

pub fn is_newer_version(current: &str, latest: &str) -> bool {
    let curr_nums = parse_version_numbers(current);
    let latest_nums = parse_version_numbers(latest);

    for (c, l) in curr_nums.iter().zip(latest_nums.iter()) {
        if l > c {
            return true;
        }
        if l < c {
            return false;
        }
    }
    latest_nums.len() > curr_nums.len()
}

pub fn check_update(
    _project_root: &Path,
    current_ver: &str,
    custom_url: Option<&str>,
) -> Result<UpdateInfo, String> {
    let endpoint = if let Some(url) = custom_url {
        url.to_string()
    } else if let Ok(env_url) = std::env::var("AUTOLINGUA_UPDATE_URL") {
        env_url
    } else {
        "https://api.github.com/repos/Ikumyon/AutoLingua2/releases/latest".to_string()
    };

    let response = ureq::get(&endpoint)
        .set("User-Agent", "AUTOlingua2-Updater")
        .set("Accept", "application/json")
        .call()
        .map_err(|e| format!("更新メタデータの取得に失敗しました: {e}"))?;

    let release: GitHubRelease = serde_json::from_reader(response.into_reader())
        .map_err(|e| format!("更新メタデータの解析に失敗しました: {e}"))?;

    let latest_ver = normalize_version(&release.tag_name).to_string();
    let current_ver_clean = normalize_version(current_ver).to_string();
    let has_update = is_newer_version(&current_ver_clean, &latest_ver);

    // OSに適合するアセットを抽出
    #[cfg(windows)]
    let os_keyword = "win";
    #[cfg(not(windows))]
    let os_keyword = "linux";

    let matching_asset = release
        .assets
        .iter()
        .find(|a| {
            let lower = a.name.to_lowercase();
            lower.contains(os_keyword) && lower.ends_with(".zip")
        })
        .or_else(|| {
            release.assets.iter().find(|a| a.name.to_lowercase().ends_with(".zip"))
        });

    let (download_url, download_size) = if let Some(asset) = matching_asset {
        (Some(asset.browser_download_url.clone()), Some(asset.size))
    } else {
        (None, None)
    };

    Ok(UpdateInfo {
        has_update,
        current_version: current_ver_clean,
        latest_version: latest_ver,
        published_at: release.published_at,
        download_url,
        download_size,
        sha256: None, // GitHub releases では別途 checksums.txt を提供するか URL 側で提供
        release_notes: release.body,
    })
}
