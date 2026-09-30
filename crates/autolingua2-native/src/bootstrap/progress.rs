use super::error;
use std::io;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Phase { Diagnostics, Modules, Plugins, Settings, Window }

impl Phase {
    pub fn parse(id: &str) -> io::Result<Self> {
        match id {
            "diagnostics" => Ok(Self::Diagnostics), "modules" => Ok(Self::Modules),
            "plugins" => Ok(Self::Plugins), "settings" => Ok(Self::Settings),
            "window" => Ok(Self::Window), _ => Err(error("Unknown startup phase")),
        }
    }
    pub fn id(self) -> &'static str {
        match self {
            Self::Diagnostics => "diagnostics", Self::Modules => "modules",
            Self::Plugins => "plugins", Self::Settings => "settings", Self::Window => "window",
        }
    }
    pub fn progress(self) -> f32 { self as u8 as f32 / 5.0 }
}

#[derive(Default)]
pub struct StartupProgress { current: Option<Phase> }
impl StartupProgress {
    /// Returns true only for a newly reached phase, independently of its display text.
    pub fn advance(&mut self, phase: Phase) -> io::Result<bool> {
        if self.current.is_some_and(|current| phase < current) {
            return Err(error("Startup phase moved backwards"));
        }
        let changed = self.current != Some(phase);
        self.current = Some(phase);
        Ok(changed)
    }
    pub fn finish(&self) -> io::Result<f32> {
        if self.current != Some(Phase::Window) { return Err(error("READY before window initialization")); }
        Ok(1.0)
    }
}
