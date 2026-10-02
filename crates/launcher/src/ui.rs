use crate::SplashWindow;

pub struct Ui(slint::Weak<SplashWindow>);
impl Ui {
    pub fn new(weak: slint::Weak<SplashWindow>) -> Self { Self(weak) }
    fn update(&self, action: impl FnOnce(SplashWindow) + Send + 'static) {
        let weak = self.0.clone();
        let _ = slint::invoke_from_event_loop(move || { if let Some(window) = weak.upgrade() { action(window); } });
    }
    pub fn status(&self, text: String) {
        self.update(move |window| window.set_status_text(text.into()));
    }
    pub fn phase(&self, text: String) {
        self.update(move |window| { window.set_status_text(text.into()); window.set_delayed(false); });
    }
    pub fn progress(&self, value: f32) {
        self.update(move |window| window.set_progress(value));
    }
    pub fn delay(&self, delayed: bool, owned: bool) {
        self.update(move |window| { window.set_delayed(delayed); window.set_can_cancel(owned); });
    }
    pub fn fail(&self, message: String) {
        self.update(move |window| {
            window.set_failed(true);
            window.set_delayed(false);
            window.set_status_text("AutoLingua Desktop を起動できませんでした".into());
            window.set_detail(message.into());
        });
    }
}
