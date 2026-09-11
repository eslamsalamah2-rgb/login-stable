import threading
import time

from tasks.input_lock import AutomationInputLock
from tasks.login_priority_gate import LoginPriorityGate
from tasks.memory_reader import ConquerMemoryReader


class PostLoginCommandRunner:
    """Runs post-login commands after selected accounts become READY.

    Login/Health is the controller. This runner is only a worker.

    Startup rule:
        all selected accounts must be READY before stage two starts.

    Watcher rule:
        if the user starts post-login work while health baselines are still
        being learned, keep a watcher thread alive instead of returning once.
        The watcher waits until all selected accounts are READY, then starts
        stage two automatically.

    Loop rule:
        after stage two starts, check only the account whose turn is next.
        If that account is not READY, stay on it and let Login/Health recover it.
        Do not advance to the next account until the current account is READY.

    Test Mode:
        background only, no foreground activation, no mouse/keyboard input.

    Real command mode:
        foreground only the current account immediately before the actual command.
    """

    def __init__(self, launcher):
        self.launcher = launcher
        self.gate = LoginPriorityGate(launcher)
        self.stop_event = threading.Event()
        self.thread = None
        self.cycle_count = 0
        self.current_index = None
        self.next_position = 0
        self.problem_key = None
        self.problem_started_at = None
        self.last_wait_log_at = 0.0
        self.lock = threading.Lock()
        self.start_gate_satisfied = False

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _feature_enabled(self, key, default=False):
        if hasattr(self.launcher, "feature_enabled"):
            try:
                return bool(self.launcher.feature_enabled(key, default))
            except Exception:
                return bool(default)

        if hasattr(self.launcher, "get_runtime_setting"):
            try:
                value = self.launcher.get_runtime_setting(key, default)
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}
            except Exception:
                return bool(default)

        return bool(default)

    def _setting_float(self, key, default, minimum=0.0):
        value = default
        if hasattr(self.launcher, "get_runtime_setting"):
            try:
                value = self.launcher.get_runtime_setting(key, default)
            except Exception:
                value = default

        try:
            value = float(value)
        except Exception:
            value = float(default)

        return max(float(minimum), value)

    def _debug_only(self):
        return self._feature_enabled("post_login_debug_only", True)

    def _has_enabled_work_module(self):
        return any(
            self._feature_enabled(key, False)
            for key in (
                "enable_auto_drop",
                "enable_sash_commands",
                "enable_monster_scan",
                "enable_movement",
            )
        )

    def _recovery_max_seconds(self):
        return self._setting_float(
            "post_login_recovery_max_seconds",
            120.0,
            minimum=30.0,
        )

    def _account_delay_seconds(self):
        return self._setting_float(
            "post_login_account_delay_seconds",
            1.0,
            minimum=0.0,
        )

    def _round_delay_seconds(self):
        return self._setting_float(
            "post_login_round_delay_seconds",
            2.0,
            minimum=0.0,
        )

    def _test_hold_seconds(self):
        return self._setting_float(
            "post_login_test_hold_seconds",
            0.70,
            minimum=0.05,
        )

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start_if_ready(self, reason="manual"):
        if not self._feature_enabled("enable_post_login_commands", True):
            print(f"Post-login commands skipped by setting - reason={reason}")
            return False

        if not self._debug_only() and not self._has_enabled_work_module():
            print(
                "Post-login commands skipped - no real command module is enabled "
                f"and Test Mode is OFF - reason={reason}"
            )
            self._set_status("أوامر الدخول: لا توجد مهمة فعلية مفعلة")
            return False

        start_gate = self.gate.all_selected_ready()
        selected = self.gate.selected_indices()
        if not selected:
            self._log_waiting(None, "NO_SELECTED_ACCOUNTS", reason)
            return False

        if not start_gate.ok:
            self._log_waiting(start_gate.account_index, start_gate.reason, reason)

        with self.lock:
            if self.is_running():
                if start_gate.ok:
                    self.start_gate_satisfied = True
                return True

            if selected and self.current_index in selected:
                self.next_position = selected.index(self.current_index)
            else:
                self.next_position = 0

            self.start_gate_satisfied = bool(start_gate.ok)
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._run_loop,
                name="PostLoginCommandRunner",
                daemon=True,
            )
            self.thread.start()

        mode = "CURRENT_ACCOUNT_BACKGROUND_TEST" if self._debug_only() else "COMMAND_LOOP"
        if start_gate.ok:
            print(
                "Post-login commands started - "
                f"reason={reason} - mode={mode} - accounts={[i + 1 for i in start_gate.ready_indices]}"
            )
            self._set_status(
                f"أوامر الدخول بدأت - {len(start_gate.ready_indices)} حساب جاهز"
            )
        else:
            account_text = "?" if start_gate.account_index is None else str(start_gate.account_index + 1)
            print(
                "Post-login commands watcher started - "
                f"reason={reason} - mode={mode} - waiting_account={account_text} - "
                f"waiting_reason={start_gate.reason}"
            )
            self._set_status("أوامر الدخول تنتظر اكتمال READY لكل الحسابات")
        return True

    def request_stop(self, reason="manual"):
        self.stop_event.set()
        print(f"Post-login commands stop requested - reason={reason}")
        self._set_status("أوامر الدخول متوقفة")

    def pause_for_login_priority(self, reason="login_priority"):
        print(f"Post-login commands yielding to Login/Health - reason={reason}")

    # ------------------------------------------------------------------
    # Recovery timeout bridge
    # ------------------------------------------------------------------

    def _log_waiting(self, problem_index, problem_reason, trigger_reason):
        now = time.time()
        if now - self.last_wait_log_at < 3.0:
            return
        self.last_wait_log_at = now

        account_text = "?" if problem_index is None else str(problem_index + 1)
        print(
            "Post-login commands waiting - "
            f"trigger={trigger_reason} - account={account_text} - reason={problem_reason}"
        )

    def _track_problem_or_recover(self, problem_index, problem_reason):
        if problem_index is None:
            self.problem_key = None
            self.problem_started_at = None
            return

        # These are waiting states, not reasons to close/reopen a game page.
        if str(problem_reason).startswith("BASELINE_PENDING") or str(problem_reason).startswith("TIMER_REQUIRED_FOR_STATE"):
            self.problem_key = None
            self.problem_started_at = None
            return

        if str(problem_reason) in {"USER_PAUSE_REQUESTED", "LOGIN_MONITOR_PAUSED", "LOGIN_SEQUENCE_RUNNING"}:
            self.problem_key = None
            self.problem_started_at = None
            return

        key = (problem_index, str(problem_reason))
        now = time.time()

        if key != self.problem_key:
            self.problem_key = key
            self.problem_started_at = now
            print(
                "Post-login commands paused for Login/Health - "
                f"account={problem_index + 1} - reason={problem_reason}"
            )
            self._set_status(
                f"أوامر الدخول متوقفة مؤقتًا - الحساب {problem_index + 1}: {problem_reason}"
            )
            return

        elapsed = now - (self.problem_started_at or now)
        max_wait = self._recovery_max_seconds()

        if elapsed < max_wait:
            return

        self.problem_started_at = now
        self._force_replace_problem_account(problem_index, problem_reason, elapsed)

    def _force_replace_problem_account(self, index, reason, elapsed):
        priority_active, priority_reason = self.gate.login_priority_active()
        if priority_active and priority_reason != "USER_PAUSE_REQUESTED":
            return

        if self.gate.account_is_recovering(index):
            return

        session = dict(self.launcher.active_sessions.get(index) or {})
        if not session:
            return

        pid = session.get("pid")
        print(
            "Post-login recovery timeout - closing/reopening current account - "
            f"account={index + 1} - pid={pid} - reason={reason} - elapsed={elapsed:.1f}s"
        )
        self._set_status(
            f"الحساب {index + 1}: مشكلة استمرت أكتر من الوقت المحدد - إغلاق وفتح صفحة جديدة"
        )

        try:
            if pid:
                ConquerMemoryReader.terminate_conquer_pid(pid)
        except Exception as error:
            print(f"Post-login forced close failed - account {index + 1}: {error}")

        try:
            self.launcher.active_sessions.pop(index, None)
            self.launcher.set_row_state(index, "working")
        except Exception:
            pass

        time.sleep(1.0)

        try:
            if hasattr(self.launcher, "_reopen_missing_account"):
                self.launcher._reopen_missing_account(index, session)
                return
        except Exception as error:
            print(f"Post-login forced reopen failed - account {index + 1}: {error}")

        try:
            if index not in self.launcher.pending_start_indices:
                self.launcher.pending_start_indices.insert(0, index)
            if not self.launcher.is_running:
                self.launcher.is_running = True
                self.launcher.run_in_thread(self.launcher.process_accounts)
        except Exception as error:
            print(f"Post-login fallback start failed - account {index + 1}: {error}")

    # ------------------------------------------------------------------
    # Command loop
    # ------------------------------------------------------------------

    def _run_loop(self):
        print("Post-login command runner loop active")

        while not self.stop_event.is_set():
            priority_active, priority_reason = self.gate.login_priority_active()
            if priority_active:
                self._log_waiting(None, priority_reason, "login_priority")
                self._sleep_interruptible(0.5)
                continue

            selected = self.gate.selected_indices()
            if not selected:
                self._log_waiting(None, "NO_SELECTED_ACCOUNTS", "loop")
                self._sleep_interruptible(1.0)
                continue

            if not self.start_gate_satisfied:
                start_gate = self.gate.all_selected_ready()
                if not start_gate.ok:
                    self._log_waiting(start_gate.account_index, start_gate.reason, "startup_gate")
                    self._track_problem_or_recover(start_gate.account_index, start_gate.reason)
                    self._sleep_interruptible(1.0)
                    continue

                self.start_gate_satisfied = True
                self.problem_key = None
                self.problem_started_at = None
                self.next_position = 0
                print(
                    "Post-login startup gate satisfied - "
                    f"accounts={[i + 1 for i in start_gate.ready_indices]}"
                )
                self._set_status(
                    f"أوامر الدخول بدأت بعد اكتمال READY - {len(start_gate.ready_indices)} حساب"
                )

            if self.next_position >= len(selected):
                self.next_position = 0

            index = selected[self.next_position]
            self.current_index = index

            current_gate = self.gate.account_ready(index)
            if not current_gate.ok:
                self._log_waiting(index, current_gate.reason, "current_account")
                self._track_problem_or_recover(index, current_gate.reason)
                self._sleep_interruptible(1.0)
                continue

            self.problem_key = None
            self.problem_started_at = None

            session = self.launcher.active_sessions.get(index)
            if not session:
                self._track_problem_or_recover(index, "NO_SESSION")
                self._sleep_interruptible(1.0)
                continue

            result = self._run_account_commands(index, session)
            if result != "OK":
                self._track_problem_or_recover(index, result)
                self._sleep_interruptible(1.0)
                continue

            previous_position = self.next_position
            self.next_position = (self.next_position + 1) % len(selected)

            if self._debug_only():
                print(
                    "Post-login current-account background test OK - "
                    f"account={index + 1} - next_account={selected[self.next_position] + 1}"
                )
                self._set_status(
                    f"اختبار أوامر الدخول: الحساب {index + 1} جاهز - التالي {selected[self.next_position] + 1}"
                )
            else:
                print(
                    "Post-login command account finished - "
                    f"account={index + 1}"
                )

            if self.next_position == 0 and previous_position != self.next_position:
                self.cycle_count += 1
                if self._debug_only():
                    print(
                        "Post-login current-account background test round finished - "
                        f"round={self.cycle_count}"
                    )
                    self._set_status(
                        f"اختبار أوامر الدخول يعمل في الخلفية - دورة {self.cycle_count}"
                    )
                else:
                    print(f"Post-login commands round finished - round={self.cycle_count}")
                    self._set_status(f"أوامر الدخول - انتهاء دورة رقم {self.cycle_count}")
                self._sleep_interruptible(self._round_delay_seconds())
            else:
                self._sleep_interruptible(self._account_delay_seconds())

        print("Post-login command runner loop stopped")

    def _activate_account_window(self, index, session):
        pid = session.get("pid")
        if not pid:
            return False, "NO_PID"

        detector = getattr(self.launcher, "window_disconnect_detector", None)
        if detector is None:
            return False, "NO_WINDOW_ACTIVATOR"

        try:
            activated = detector.activate_main_window(pid)
        except Exception as error:
            print(
                "Post-login foreground error - "
                f"account={index + 1} - pid={pid} - {error}"
            )
            return False, "FOREGROUND_ERROR"

        if not activated:
            print(
                "Post-login foreground failed - "
                f"account={index + 1} - pid={pid}"
            )
            return False, "FOREGROUND_FAILED"

        print(
            "Post-login foreground ready - "
            f"account={index + 1} - pid={pid}"
        )
        time.sleep(0.15)
        return True, "FOREGROUND_OK"

    def _run_account_commands(self, index, session):
        pid = session.get("pid")
        page_name = session.get("page_name", "")
        self.current_index = index

        try:
            if self._debug_only():
                current_gate = self.gate.account_ready(index)
                if not current_gate.ok:
                    return current_gate.reason

                print(
                    "Post-login command step - "
                    f"account={index + 1} - pid={pid} - name={page_name!r} - "
                    "stage=CURRENT_ACCOUNT_BACKGROUND_TEST_ONLY"
                )
                self._set_status(
                    f"اختبار أوامر الدخول: فحص الحساب {index + 1} في الخلفية فقط"
                )
                self._sleep_interruptible(self._test_hold_seconds())
                return "OK"

            with AutomationInputLock.hold("PostLoginCommandRunner.real_command"):
                activated, activate_reason = self._activate_account_window(index, session)
                if not activated:
                    return activate_reason

                current_gate = self.gate.account_ready(index)
                if not current_gate.ok:
                    return current_gate.reason

                # Real command modules will be called here one by one.
                # Foreground activation happens only for the current account
                # immediately before executing its real command.
                print(
                    "Post-login command step - "
                    f"account={index + 1} - pid={pid} - name={page_name!r} - "
                    "stage=READY_FOR_REAL_COMMANDS"
                )
                self._set_status(
                    f"أوامر الدخول: الحساب {index + 1} على الوش وجاهز للتنفيذ"
                )
                time.sleep(0.05)
            return "OK"

        except Exception as error:
            print(f"Post-login command step error - account={index + 1}: {error}")
            return "COMMAND_ERROR"

    def _sleep_interruptible(self, seconds):
        end = time.time() + max(0.0, float(seconds))
        while not self.stop_event.is_set() and time.time() < end:
            time.sleep(min(0.2, max(0.0, end - time.time())))

    def _set_status(self, text):
        try:
            self.launcher.set_status(text)
        except Exception:
            pass
