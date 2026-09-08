from tasks.memory_reader import ConquerMemoryReader
from tasks.timer_heartbeat_detector import TimerHeartbeatDetector
from health_launcher import HealthAwareLauncher


def _patched_verify_with_timer_before_recovery(self, row_index, session):
    """Treat any state seen while the exact PID timer is missing/static as ambiguous.

    This prevents recovery from learning a logout/error memory value as a new
    healthy baseline just because the character name in memory stayed unchanged.
    """
    if self.is_running or self._timer_stop_requested():
        return

    pid = session.get("pid")
    if not pid or pid not in ConquerMemoryReader.list_conquer_pids():
        self._reopen_missing_account(row_index, session)
        return

    self.set_status(
        f"الحساب {row_index + 1}: فحص تأكيدي للعداد قبل إعادة الدخول..."
    )

    result = self.timer_heartbeat_detector.check(
        pid,
        stop_check=self._timer_stop_requested,
    )

    print(
        f"Timer confirmation - account {row_index + 1} - PID {pid} - {result}"
    )

    if result == TimerHeartbeatDetector.ACTIVE:
        current_name, current_state = self._read_health(pid)

        if self._state_requires_timer(current_state):
            expected_name = session.get("page_name", "")
            if current_name == expected_name:
                self.set_row_state(row_index, "success", expected_name)
                self.set_status(
                    f"الحساب {row_index + 1}: State {current_state} متكرر لكن عداد الثواني شغال داخل نفس الصفحة"
                )
                print(
                    f"Timer-authoritative HEALTHY - account {row_index + 1} - "
                    f"PID {pid} - State {current_state} - baseline preserved "
                    f"as {session.get('healthy_state')}"
                )
                return

        self._refresh_baseline_from_live_page(row_index, session)
        return

    # Important: gate ANY state observed while gameplay timer proof fails.
    # Do not require it to equal the previous healthy baseline.
    current_name, current_state = self._read_health(pid)
    if current_state is not None:
        self._mark_state_timer_gated(
            current_state,
            row_index,
            pid,
            f"TIMER_{result}",
        )

    if result == TimerHeartbeatDetector.MISSING:
        print(
            f"Timer confirmation - account {row_index + 1} - PID {pid} - "
            "timer not present inside this PID window; state is now timer-gated and recovery is required"
        )

    if self._timer_stop_requested():
        return

    self._recover_logged_out_account(row_index, session)


def apply_health_recovery_patch():
    HealthAwareLauncher._verify_with_timer_before_recovery = _patched_verify_with_timer_before_recovery


apply_health_recovery_patch()
