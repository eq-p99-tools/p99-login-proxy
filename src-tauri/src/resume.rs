//! Rebind the UDP listener after the machine wakes.
//!
//! Windows tears down or blackholes a UDP socket across sleep, and the receive
//! loop keeps using that socket. The Python app restarts its listener on
//! `PBT_APMRESUMEAUTOMATIC`. The same notification is registered here.
//! `Instant` cannot see the gap: it shares Tokio's monotonic clock, which does
//! not advance while the system is suspended.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use runtime::AppSupervisor;
use tokio::sync::Mutex;

const RETRY_ATTEMPTS: u32 = 5;
const RETRY_DELAY: Duration = Duration::from_secs(2);
const BOUNCE_DEBOUNCE: Duration = Duration::from_secs(5);

const WALL_CLOCK_TICK: Duration = Duration::from_secs(10);
const WALL_CLOCK_GAP: Duration = Duration::from_secs(30);

static LAST_RESUME_BOUNCE_MS: AtomicU64 = AtomicU64::new(0);

pub fn spawn_resume_monitor(supervisor: Arc<Mutex<AppSupervisor>>) {
    #[cfg(windows)]
    {
        if register_suspend_resume(supervisor.clone()) {
            return;
        }
        tracing::warn!("power resume notification unavailable; watching the wall clock instead");
    }
    spawn_wall_clock_resume_monitor(supervisor);
}

fn spawn_wall_clock_resume_monitor(supervisor: Arc<Mutex<AppSupervisor>>) {
    tauri::async_runtime::spawn(async move {
        loop {
            let before = SystemTime::now();
            tokio::time::sleep(WALL_CLOCK_TICK).await;
            let elapsed = SystemTime::now()
                .duration_since(before)
                .unwrap_or(Duration::ZERO);
            if wall_clock_gap_is_resume(elapsed, WALL_CLOCK_TICK, WALL_CLOCK_GAP) {
                schedule_resume_bounce(supervisor.clone());
            }
        }
    });
}

/// A suspend shows up as wall time jumping far past the timer tick. A normal
/// tick stays near `tick` even when the scheduler is a little late.
fn wall_clock_gap_is_resume(elapsed: Duration, tick: Duration, gap: Duration) -> bool {
    elapsed > tick + gap
}

fn schedule_resume_bounce(supervisor: Arc<Mutex<AppSupervisor>>) {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;
    let previous = LAST_RESUME_BOUNCE_MS.load(Ordering::Relaxed);
    if now_ms.saturating_sub(previous) < BOUNCE_DEBOUNCE.as_millis() as u64 {
        return;
    }
    LAST_RESUME_BOUNCE_MS.store(now_ms, Ordering::Relaxed);
    tauri::async_runtime::spawn(restart_listener_after_resume(supervisor));
}

/// Rebind the listener. The network stack is often still down at the moment
/// of resume, so a failed bind is retried without holding the supervisor lock.
async fn restart_listener_after_resume(supervisor: Arc<Mutex<AppSupervisor>>) {
    let mut was_running = false;
    for attempt in 1..=RETRY_ATTEMPTS {
        let result = {
            let mut sup = supervisor.lock().await;
            if attempt == 1 {
                was_running = sup.udp_listener_running();
                if !was_running {
                    return;
                }
                sup.bounce_proxy_transport().await
            } else if !was_running || sup.udp_listener_running() {
                return;
            } else {
                sup.start_proxy().await
            }
        };
        match result {
            Ok(()) => {
                if attempt > 1 {
                    tracing::info!(attempt, "UDP proxy listener restarted after resume");
                }
                return;
            }
            Err(error) => {
                tracing::warn!(
                    error = %error,
                    attempt,
                    "resume proxy restart failed"
                );
                if attempt < RETRY_ATTEMPTS {
                    tokio::time::sleep(RETRY_DELAY).await;
                }
            }
        }
    }
}

#[cfg(windows)]
#[allow(unsafe_code)]
fn register_suspend_resume(supervisor: Arc<Mutex<AppSupervisor>>) -> bool {
    use std::ffi::c_void;

    use windows_sys::Win32::System::Power::{
        PowerRegisterSuspendResumeNotification, DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::DEVICE_NOTIFY_CALLBACK;

    let context = Box::leak(Box::new(supervisor));
    let params = Box::leak(Box::new(DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS {
        Callback: Some(on_suspend_resume),
        Context: (context as *mut Arc<Mutex<AppSupervisor>>).cast(),
    }));

    let mut registration: *mut c_void = std::ptr::null_mut();
    // SAFETY: `params` and `context` are leaked for the process lifetime, which
    // is as long as the OS keeps this registration. The callback only reads the
    // leaked `Arc` and hops onto the async runtime.
    let status = unsafe {
        PowerRegisterSuspendResumeNotification(
            DEVICE_NOTIFY_CALLBACK,
            (params as *mut DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS).cast(),
            &mut registration,
        )
    };
    if status != 0 {
        tracing::warn!(status, "PowerRegisterSuspendResumeNotification failed");
        return false;
    }
    let _ = registration;
    true
}

#[cfg(windows)]
#[allow(unsafe_code)]
unsafe extern "system" fn on_suspend_resume(
    context: *const std::ffi::c_void,
    event_type: u32,
    _setting: *const std::ffi::c_void,
) -> u32 {
    use windows_sys::Win32::UI::WindowsAndMessaging::PBT_APMRESUMEAUTOMATIC;

    if event_type != PBT_APMRESUMEAUTOMATIC || context.is_null() {
        return 0;
    }
    // SAFETY: `context` is the `Arc` leaked in `register_suspend_resume`.
    let supervisor = unsafe { &*context.cast::<Arc<Mutex<AppSupervisor>>>() }.clone();
    schedule_resume_bounce(supervisor);
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_suspend_sized_wall_gap_is_a_resume() {
        assert!(wall_clock_gap_is_resume(
            Duration::from_secs(3_600),
            WALL_CLOCK_TICK,
            WALL_CLOCK_GAP,
        ));
    }

    #[test]
    fn a_normal_tick_is_not_a_resume() {
        assert!(!wall_clock_gap_is_resume(
            Duration::from_secs(11),
            WALL_CLOCK_TICK,
            WALL_CLOCK_GAP,
        ));
    }

    #[test]
    fn the_resume_threshold_is_just_past_the_tick_plus_gap() {
        assert!(!wall_clock_gap_is_resume(
            WALL_CLOCK_TICK + WALL_CLOCK_GAP,
            WALL_CLOCK_TICK,
            WALL_CLOCK_GAP,
        ));
        assert!(wall_clock_gap_is_resume(
            WALL_CLOCK_TICK + WALL_CLOCK_GAP + Duration::from_millis(1),
            WALL_CLOCK_TICK,
            WALL_CLOCK_GAP,
        ));
    }
}
