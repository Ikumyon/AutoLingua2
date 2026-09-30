use std::time::Duration;

/// Elapsed durations come from the caller, so timeout tests never sleep.
pub struct StartupClock {
    last_progress: Duration,
    cancelling_since: Option<Duration>,
}
impl StartupClock {
    pub fn new() -> Self { Self { last_progress: Duration::ZERO, cancelling_since: None } }
    pub fn progress(&mut self, now: Duration) { self.last_progress = now; }
    pub fn delayed(&self, now: Duration) -> bool {
        self.cancelling_since.is_none() && now.saturating_sub(self.last_progress) >= Duration::from_secs(60)
    }
    pub fn cancel(&mut self, now: Duration) { self.cancelling_since.get_or_insert(now); }
    pub fn cancelling(&self) -> bool { self.cancelling_since.is_some() }
    pub fn must_kill(&self, now: Duration) -> bool {
        self.cancelling_since.is_some_and(|start| now.saturating_sub(start) >= Duration::from_secs(5))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn delay_is_only_a_notice_and_real_progress_resets_it() {
        let mut clock = StartupClock::new();
        assert!(!clock.delayed(Duration::from_secs(59)));
        assert!(clock.delayed(Duration::from_secs(60)));
        assert!(!clock.must_kill(Duration::from_secs(600)));
        clock.progress(Duration::from_secs(65));
        assert!(!clock.delayed(Duration::from_secs(66)));
    }
    #[test]
    fn cancellation_grace_period_is_not_reset_by_repeated_clicks() {
        let mut clock = StartupClock::new();
        clock.cancel(Duration::from_secs(70));
        clock.cancel(Duration::from_secs(73));
        assert!(!clock.must_kill(Duration::from_secs(74)));
        assert!(clock.must_kill(Duration::from_secs(75)));
    }
}
