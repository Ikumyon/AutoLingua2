fn main() {
    slint_build::compile("ui/UpdateProgressDialog.slint").unwrap();

    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        let version = include_str!("../../VERSION").trim();
        res.set("FileVersion", version);
        res.set("ProductVersion", version);
        let parts: Vec<u64> = version.split('.').map(|part| part.parse().unwrap()).collect();
        assert_eq!(parts.len(), 3);
        let numeric = (parts[0] << 48) | (parts[1] << 32) | (parts[2] << 16);
        res.set_version_info(winres::VersionInfo::FILEVERSION, numeric);
        res.set_version_info(winres::VersionInfo::PRODUCTVERSION, numeric);
        res.set_icon("../../assets/images/app.ico");
        res.compile().unwrap();
    }
}
