fn main() {
    slint_build::compile("ui/UpdateProgressDialog.slint").unwrap();

    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../../assets/images/app.ico");
        res.compile().unwrap();
    }
}
