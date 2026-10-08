use std::io;
use std::path::Path;

pub fn available() -> bool { cfg!(windows) }

pub fn project_from_uri(value: &str) -> io::Result<String> {
    let uri = url::Url::parse(value).map_err(io::Error::other)?;
    let pairs: Vec<_> = uri.query_pairs().collect();
    if uri.scheme() != "autolingua2" || uri.host_str() != Some("source-update")
        || !uri.username().is_empty() || uri.password().is_some() || uri.port().is_some()
        || !matches!(uri.path(), "" | "/") || uri.fragment().is_some()
        || pairs.len() != 1 || pairs[0].0 != "source" {
        return Err(io::Error::other("Invalid source notification URI"));
    }
    let project = pairs[0].1.to_string();
    let path = Path::new(&project);
    if !path.is_absolute() {
        return Err(io::Error::other("Invalid notification project path"));
    }
    Ok(project)
}

#[cfg(windows)]
mod implementation {
    use super::*;
    use std::os::windows::ffi::OsStrExt;
    use std::process::Command;
    use windows::core::HSTRING;
    use windows::Data::Xml::Dom::XmlDocument;
    use windows::UI::Notifications::{ToastNotification, ToastNotificationManager};
    use windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};

    const APP_ID: &str = "autolingua2.source-updates";

    fn registry(key: &str, name: Option<&str>, value: &str) -> io::Result<()> {
        let mut command = Command::new("reg.exe");
        command.args(["add", key]);
        if let Some(name) = name { command.args(["/v", name]); } else { command.arg("/ve"); }
        command.args(["/t", "REG_SZ", "/d", value, "/f"]);
        super::super::os::detach(&mut command);
        let output = command.output()?;
        if !output.status.success() {
            return Err(io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()));
        }
        Ok(())
    }

    pub fn setup(launcher: &[String], icon: &str) -> io::Result<()> {
        let (executable, _) = launcher.split_first().ok_or_else(|| io::Error::other("Missing launcher command"))?;
        if !Path::new(executable).is_file() { return Err(io::Error::other("Notification launcher is missing")); }
        if launcher.iter().any(|part| part.contains(['"', '\n', '\r'])) {
            return Err(io::Error::other("Invalid notification launcher command"));
        }
        let command = launcher.iter().map(|part| format!("\"{part}\""))
            .collect::<Vec<_>>().join(" ") + " \"%1\"";
        let app_key = format!("HKCU\\Software\\Classes\\AppUserModelId\\{APP_ID}");
        registry(&app_key, Some("DisplayName"), "AUTOlingua2")?;
        registry(&app_key, Some("IconUri"), icon)?;
        registry("HKCU\\Software\\Classes\\autolingua2", None, "URL:AUTOlingua2")?;
        registry("HKCU\\Software\\Classes\\autolingua2", Some("URL Protocol"), "")?;
        registry("HKCU\\Software\\Classes\\autolingua2\\shell\\open\\command", None, &command)
    }

    #[link(name = "winmm")]
    extern "system" {
        fn PlaySoundW(sound: *const u16, module: usize, flags: u32) -> i32;
    }

    pub fn preview_sound(path: &str) -> io::Result<()> {
        let (name, flags) = if path.is_empty() {
            ("SystemNotification", 0x0001 | 0x00010000)
        } else {
            let file = Path::new(path);
            if !file.is_file() || !file.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("wav")) {
                return Err(io::Error::other("Notification sound must be an existing WAV file"));
            }
            (path, 0x0001 | 0x0002 | 0x00020000)
        };
        let wide: Vec<u16> = std::ffi::OsStr::new(name).encode_wide().chain(Some(0)).collect();
        if unsafe { PlaySoundW(wide.as_ptr(), 0, flags) } == 0 {
            return Err(io::Error::other("Unable to play notification sound"));
        }
        Ok(())
    }

    fn escape(text: &str) -> String {
        text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
            .replace('"', "&quot;").replace('\'', "&apos;")
    }

    struct Apartment;
    impl Drop for Apartment { fn drop(&mut self) { unsafe { RoUninitialize(); } } }

    pub fn show(project: &str, name: &str, message: &str, icon: &str, sound: &str) -> io::Result<()> {
        let mut uri = url::Url::parse("autolingua2://source-update").map_err(io::Error::other)?;
        uri.query_pairs_mut().append_pair("source", project);
        let image = if icon.is_empty() {
            String::new()
        } else {
            let path = Path::new(icon);
            if !path.is_file() { return Err(io::Error::other("Notification image is missing")); }
            let file_uri = url::Url::from_file_path(path).map_err(|_| io::Error::other("Invalid notification image path"))?;
            format!("<image placement=\"appLogoOverride\" src=\"{}\"/>", escape(file_uri.as_str()))
        };
        if !sound.is_empty() && !Path::new(sound).is_file() {
            return Err(io::Error::other("Notification sound is missing"));
        }
        let audio = if sound.is_empty() { "" } else { "<audio silent=\"true\"/>" };
        let xml = format!("<toast activationType=\"protocol\" launch=\"{}\"><visual><binding template=\"ToastGeneric\">{image}<text>{}</text><text>{}</text></binding></visual>{audio}</toast>",
            escape(uri.as_str()), escape(name), escape(message));
        unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.map_err(io::Error::other)?;
        let _apartment = Apartment;
        let document = XmlDocument::new().map_err(io::Error::other)?;
        document.LoadXml(&HSTRING::from(xml)).map_err(io::Error::other)?;
        let toast = ToastNotification::CreateToastNotification(&document).map_err(io::Error::other)?;
        ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(APP_ID))
            .and_then(|notifier| notifier.Show(&toast)).map_err(io::Error::other)?;
        if !sound.is_empty() { preview_sound(sound)?; }
        Ok(())
    }
}

#[cfg(not(windows))]
mod implementation {
    use super::*;
    pub fn setup(_launcher: &[String], _icon: &str) -> io::Result<()> { Ok(()) }
    pub fn preview_sound(_path: &str) -> io::Result<()> { Err(io::Error::new(io::ErrorKind::Unsupported, "Notifications are available on Windows only")) }
    pub fn show(_project: &str, _name: &str, _message: &str, _icon: &str, _sound: &str) -> io::Result<()> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "Notifications are available on Windows only"))
    }
}

pub use implementation::{preview_sound, setup, show};
