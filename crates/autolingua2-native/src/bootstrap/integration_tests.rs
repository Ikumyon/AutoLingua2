use super::*;
use std::io::Write;
use std::thread;
use std::time::{Duration, Instant};
use std::sync::{mpsc, Arc, atomic::{AtomicBool, Ordering}};

struct TestContext(Context);
impl TestContext {
    fn new() -> Self {
        let name = format!("autolingua2-test-{}", &token().unwrap()[..16]);
        let directory = os::runtime_root().unwrap().join(&name);
        os::private_directory(&directory).unwrap();
        Self(Context { directory, name })
    }
}
impl Drop for TestContext {
    fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0.directory); }
}

fn accept(listener: &mut Listener) -> Connection {
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(stream) = listener.accept().unwrap() { return Connection::new(stream); }
        assert!(Instant::now() < deadline, "No bootstrap connection");
        thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn exclusive_locks_are_released_without_deleting_the_lock_file() {
    let context = TestContext::new();
    let lock = context.0.lock("core").unwrap().unwrap();
    assert!(context.0.core_running().unwrap());
    assert!(context.0.lock("core").unwrap().is_none());
    assert!(context.0.lock("startup").unwrap().is_some());
    drop(lock);
    assert!(!context.0.core_running().unwrap());
    assert!(context.0.directory.join("core.lock").exists());
}

#[test]
fn ready_releases_launcher_but_core_keeps_activation_and_restart_endpoint() {
    let context = TestContext::new();
    let credential = token().unwrap();
    let mut listener = Listener::bind(&context.0.endpoint(&format!("boot-{}", &credential[..16]))).unwrap();
    let expected = credential.clone();
    let (phase_sender, phases) = mpsc::channel();
    let server = thread::spawn(move || {
        let mut connection = accept(&mut listener);
        assert_eq!(connection.receive(Duration::from_secs(2)).unwrap(), Message::Hello(expected));
        connection.send(&Message::Ack).unwrap();
        loop {
            let message = connection.receive(Duration::from_secs(3)).unwrap();
            connection.send(&Message::Ack).unwrap();
            match message {
                Message::Phase(_, text) => phase_sender.send(text).unwrap(),
                Message::Ping => (),
                Message::Ready => {
                    assert_eq!(connection.receive(Duration::from_secs(2)).unwrap(), Message::Ack);
                    break;
                }
                _ => panic!("Unexpected message"),
            }
        }
    });
    let mut session = core::Session::connect(context.0.clone(), credential.clone()).unwrap();
    assert!(core::Session::connect(context.0.clone(), credential).is_err());
    session.notify(Message::Phase(Phase::Plugins, "plugins".into())).unwrap();
    assert_eq!(phases.recv_timeout(Duration::from_secs(2)).unwrap(), "plugins");
    activate(&context.0).unwrap();
    assert!(!session.take_activation()); // Retained until READY.
    session.notify(Message::Ready).unwrap();
    server.join().unwrap();
    assert!(session.take_activation());
    assert!(!session.take_activation());
    activate(&context.0).unwrap();
    assert!(session.take_activation());
    let ticket = session.prepare_restart().unwrap();
    Connection::connect(&context.0.endpoint("core"), Duration::from_secs(2)).unwrap()
        .request(&Message::Restart(ticket)).unwrap();
    session.wait_restart(Duration::from_secs(2)).unwrap();
    assert!(context.0.core_running().unwrap());
    session.close();
    assert!(!context.0.core_running().unwrap());
}

#[test]
fn wrong_startup_credential_does_not_create_a_live_session() {
    let context = TestContext::new();
    let credential = token().unwrap();
    let mut listener = Listener::bind(&context.0.endpoint(&format!("boot-{}", &credential[..16]))).unwrap();
    let server = thread::spawn(move || {
        let mut channel = accept(&mut listener);
        assert!(matches!(channel.receive(Duration::from_secs(2)).unwrap(), Message::Hello(_)));
        channel.send(&Message::Cancel).unwrap();
        // Keep the server alive until the client has read its rejection.
        let _ = channel.receive(Duration::from_secs(1));
    });
    assert!(core::Session::connect(context.0.clone(), credential).is_err());
    server.join().unwrap();
    assert!(!context.0.core_running().unwrap());
}

#[test]
fn launcher_disconnect_is_a_startup_failure() {
    let context = TestContext::new();
    let credential = token().unwrap();
    let mut listener = Listener::bind(&context.0.endpoint(&format!("boot-{}", &credential[..16]))).unwrap();
    let disconnect = Arc::new(AtomicBool::new(false));
    let end = disconnect.clone();
    let server = thread::spawn(move || {
        let mut channel = accept(&mut listener);
        channel.receive(Duration::from_secs(2)).unwrap();
        channel.send(&Message::Ack).unwrap();
        while !end.load(Ordering::Acquire) { thread::sleep(Duration::from_millis(5)); }
    });
    let mut session = core::Session::connect(context.0.clone(), credential).unwrap();
    disconnect.store(true, Ordering::Release);
    server.join().unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    while session.check().is_ok() {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(10));
    }
    session.close();
}

#[test]
fn truncated_and_oversized_frames_are_rejected() {
    let context = TestContext::new();
    let path = context.0.endpoint("frames");
    let mut listener = Listener::bind(&path).unwrap();
    let mut client = Stream::connect(&path).unwrap();
    let mut server = accept(&mut listener);
    client.write_all(&((MAX_FRAME + 1) as u32).to_le_bytes()).unwrap();
    assert!(server.receive(Duration::from_secs(1)).is_err());
}

#[test]
fn update_placeholder_is_not_a_successful_check() {
    assert_eq!(update_status().0, "unavailable");
    assert!(update_status().1.contains("未実装"));
}
