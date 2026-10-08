use crate::logging::log_file;
use autolingua2_native::{bootstrap::error, platform};
use std::ffi::OsString;
use std::io;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};

pub(super) struct Target {
    executable: PathBuf, args: Vec<OsString>, root: PathBuf,
    pub(super) development: Option<PathBuf>, source_update: Option<String>,
}
impl Target {
    pub(super) fn resolve() -> io::Result<Self> {
        let mut args = std::env::args_os().skip(1);
        let mut forwarded = Vec::new();
        let mut development = None;
        let mut source_update = None;
        while let Some(arg) = args.next() {
            if arg == "--development-root" {
                if development.is_some() { return Err(error("Duplicate development root")); }
                development = Some(PathBuf::from(args.next().ok_or_else(|| error("Missing development root"))?).canonicalize()?);
            } else if arg.to_str().is_some_and(|value| value.starts_with("autolingua2:")) {
                let uri = arg.to_str().ok_or_else(|| error("Invalid notification URI"))?;
                if source_update.is_some() { return Err(error("Duplicate source update request")); }
                let project = autolingua2_native::source_watch::notification::project_from_uri(uri)?;
                forwarded.push(OsString::from("--source-update"));
                forwarded.push(OsString::from(&project));
                source_update = Some(project);
            } else if arg == "--source-update" {
                if source_update.is_some() { return Err(error("Duplicate source update request")); }
                let project = args.next().ok_or_else(|| error("Missing source update project"))?;
                source_update = Some(project.to_str().ok_or_else(|| error("Invalid project path"))?.to_string());
                forwarded.push(arg);
                forwarded.push(project);
            } else { forwarded.push(arg); }
        }
        let (root, executable, mut arguments) = if let Some(root) = &development {
            let python = root.join(platform::development_python());
            (root.clone(), python, vec![root.join("main.py").into_os_string()])
        } else {
            let exe = std::env::current_exe()?;
            let root = exe.parent().ok_or_else(|| error("Launcher directory unavailable"))?.to_path_buf();
            let sub = root.join("core").join(platform::executable_name("autolingua2_core"));
            let core = if sub.is_file() { sub } else { root.join(platform::executable_name("autolingua2_core")) };
            (root, core, vec![])
        };
        if !executable.is_file() { return Err(error(format!("実行対象がありません: {}", executable.display()))); }
        arguments.extend(forwarded);
        Ok(Self { executable, args: arguments, root, development, source_update })
    }

    pub(super) fn activate(&self, context: &autolingua2_native::bootstrap::Context) -> io::Result<()> {
        use autolingua2_native::bootstrap::{activate, Connection, Message};
        if let Some(project) = &self.source_update {
            Connection::connect(&context.endpoint("core"), std::time::Duration::from_secs(2))?
                .request(&Message::SourceUpdate(project.clone()))
        } else { activate(context) }
    }

    pub(super) fn spawn(&self, credential: &str) -> io::Result<Child> {
        let mut command = Command::new(&self.executable);
        command.args(&self.args).current_dir(&self.root)
            .env("AUTOLINGUA_BOOT_TOKEN", credential)
            .env("AUTOLINGUA_LAUNCHER", std::env::current_exe()?)
            .env_remove("AUTOLINGUA_RESTART_TICKET").env_remove("AUTOLINGUA_RESTART_PID")
            .env("PYINSTALLER_RESET_ENVIRONMENT", "1")
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::from(log_file()?));
        if let Some(root) = &self.development {
            command.env("AUTOLINGUA_DEVELOPMENT_ROOT", root);
            command.env("PYTHONPATH", std::env::join_paths([root.join("build/native"), root.join("src")]).map_err(error)?);
        } else { command.env_remove("AUTOLINGUA_DEVELOPMENT_ROOT"); }
        platform::configure_core_command(&mut command);
        command.spawn().map_err(|err| error(format!("本体プロセスの生成に失敗しました: {err}")))
    }
}
