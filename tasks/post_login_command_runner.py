import threading
import time

from tasks.input_lock import AutomationInputLock
from tasks.memory_reader import ConquerMemoryReader


class PostLoginCommandRunner:
    """Runs post-login commands after selected accounts become READY.

    Stage 1 is an orchestration/safety layer only. It does not drop/use items yet.
    The goal is to prove the control flow:
      login first -> commands second -> health/recovery always has priority.
    """

    def __init__(self, launcher):
        self.launcher = launcher
        self.stop_event = threading.Event()
        self.thread = None
        self.cycle_count = 0
        self.current_index = None
        self.problem_key = None
        self.problem_started_at = None
        self.last_wait_log_at = 0.0
        self.lock = threading.Lock()

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

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start_if_ready(self, reason="manual"):
        if not self._feature_enabled("enable_post_login_commands", True):
            print(f"Post-login commands skipped by setting - reason={reason}")
            return False

        ok, ready_indices, problem_index, problem_reason = self._selected_ready_state()
        if not ok:
            self._log_waiting(problem_index, problem_reason, reason)
            return False

        with self.lock:
            if self.is_running():
                return True

            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._run_loop,
                name="PostLoginCommandRunner",
                daemon=True,
            )
            self.thread.start()

        print(
            "Post-login commands started - "
            f"reason={reason} - accounts={[i + 1 for i in ready_indices]}"
        )
        self._set_status(
            f"أوامر الدخول بدأت - {len(ready_indices)} حساب جاهز"
        )
        return True

    def request_stop(self, reason="manual"):
        self.stop_event.set()
        print(f"Post-login commands stop requested - reason={reason}")
        self._set_status("أوامر الدخول متوقفة")

    def pause_for_login_priority(self, reason="login_priority"):
        # The loop is cooperative. It will see is_running/recovery flags and wait.
        print(f"Post-login commands yielding to Login/Health - reason={reason}")

    # ------------------------------------------------------------------
    # Readiness checks
    # ------------------------------------------------------------------

    def _selected_indices(self):
        try:
            if hasattr(self.launcher, "_selected_indices"):
                return list(self.launcher._selected_indices())
        except Exception:
            pass

        try:
            return sorted(int(i) for i in self.launcher.active_sessions.keys())
        except Exception:
            return []

    def _account_is_recovering(self, index):
        try:
            with self.launcher.recovering_accounts_lock:
                return index in self.launcher.recovering_accounts
        except Exception:
            return False

    def _read_health(self, pid):
        try:
            if hasattr(self.launcher, "_read_health"):
                return self.launcher._read_health(pid)
        except Exception as error:
            print(f"Post-login health read failed via launcher - PID {pid}: {error}")

        reader = None
        try:
            reader = ConquerMemoryReader(pid)
            return reader.read_name() or "", reader.read_state()
        except Exception as error:
            print(f"Post-login health read failed - PID {pid}: {error}")
            return None, None
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass

    def _is_ready_for_commands(self, index):
        if self.launcher.is_running:
            return False, "LOGIN_SEQUENCE_RUNNING"

        if self._account_is_recovering(index):
            return False, "RECOVERING"

        session = self.launcher.active_sessions.get(index)
        if not session:
            return False, "NO_SESSION"

        pid = session.get("pid")
        if not pid:
            return False, "NO_PID"

        live_pids = set(ConquerMemoryReader.list_conquer_pids())
        if pid not in live_pids:
            return False, "PID_MISSING"

        try:
            detector = getattr(self.launcher, "window_disconnect_detector", None)
            if detector is not None and detector.has_disconnect_dialog(pid):
                return False, "DISCONNECTED_DIALOG"
        except Exception as error:
            print(f"Post-login disconnect check failed - account {index + 1}: {error}")

        current_name, current_state = self._read_health(pid)
        if current_name is None or current_state is None:
            return False, "MEMORY_READ_FAILED"

        expected_name = session.get("page_name", "")
        if not expected_name and 0 <= index < len(self.launcher.accounts_data):
            expected_name = self.launcher.accounts_data[index].get("character_name", "")

        if expected_name and current_name != expected_name:
            return False, f"NAME_MISMATCH({current_name!r}!={expected_name!r})"

        healthy_state = session.get("healthy_state")
        if healthy_state is None:
            return False, "BASELINE_PENDING"

        try:
            if hasattr(self.launcher, "_state_requires_timer") and self.launcher._state_requires_timer(current_state):
                return False, f"TIMER_REQUIRED_FOR_STATE({current_state})"
        except Exception:
            pass

        if current_state != healthy_state:
            return False, f"STATE_MISMATCH({current_state}!={healthy_state})"

        return True, "READY"

    def _selected_ready_state(self):
        selected = self._selected_indices()
        if not selected:
            return False, [], None, "NO_SELECTED_ACCOUNTS"

        ready = []
        for index in selected:
            ok, reason = self._is_ready_for_commands(index)
            if not ok:
                return False, ready, index, reason
            ready.append(index)

        return True, ready, None, "READY"

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
        if self.launcher.is_running or self._account_is_recovering(index):
            return

        session = dict(self.launcher.active_sessions.get(index) or {})
        if not session:
            return

        pid = session.get("pid")
        print(
            "Post-login recovery timeout - closing/reopening account - "
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
            ok, ready_indices, problem_index, problem_reason = self._selected_ready_state()

            if not ok:
                self._log_waiting(problem_index, problem_reason, "loop")
                self._track_problem_or_recover(problem_index, problem_reason)
                self._sleep_interruptible(1.0)
                continue

            self.problem_key = None
            self.problem_started_at = None

            for index in ready_indices:
                if self.stop_event.is_set():
                    break

                ok, reason = self._is_ready_for_commands(index)
                if not ok:
                    self._track_problem_or_recover(index, reason)
                    break

                session = self.launcher.active_sessions.get(index)
                if not session:
                    self._track_problem_or_recover(index, "NO_SESSION")
                    break

                result = self._run_account_commands(index, session)
                if result != "OK":
                    self._track_problem_or_recover(index, result)
                    break

                self._sleep_interruptible(self._account_delay_seconds())

            self.cycle_count += 1
            print(f"Post-login commands round finished - round={self.cycle_count}")
            self._set_status(f"أوامر الدخول - انتهاء دورة رقم {self.cycle_count}")
            self._sleep_interruptible(self._round_delay_seconds())

        print("Post-login command runner loop stopped")

    def _run_account_commands(self, index, session):
        pid = session.get("pid")
        page_name = session.get("page_name", "")
        self.current_index = index

        try:
            with AutomationInputLock.hold("PostLoginCommandRunner.stage1"):
                # Stage 1 intentionally does not click or type.
                # Next stages will put Drop/Use/Sash here.
                print(
                    "Post-login command step - "
                    f"account={index + 1} - pid={pid} - name={page_name!r} - "
                    "stage=READY_CHECK_ONLY"
                )
                self._set_status(
                    f"أوامر الدخول: الحساب {index + 1} جاهز - مرحلة اختبار فقط"
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
