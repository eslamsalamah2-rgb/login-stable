import time

from health_launcher import HealthAwareLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask
from tasks.timer_heartbeat_detector import TimerHeartbeatDetector


def _recover_logged_out_account(self, row_index, session):
    """Relog an unhealthy page; if it is not READY in 90s, replace only that page."""
    if not self._mark_recovery_started(row_index):
        return

    try:
        if self.is_running or self.pause_requested or self.monitor_pause_event.is_set():
            return

        with self.recovery_lock:
            if self.pause_requested or self.monitor_pause_event.is_set():
                return

            pid = session.get("pid")
            username = session.get("username", "")
            password = session.get("password", "")
            expected_name = session.get("page_name", "")
            path = self.path_entry.get().strip()

            if not pid or not username or not password or not path:
                self.set_row_state(row_index, "error")
                return

            recovery_deadline = time.time() + 90.0

            def reopen_same_account(reason):
                print(
                    f"Recovery timeout/reopen - account {row_index + 1} - "
                    f"PID {pid} - Reason: {reason}"
                )
                self.set_row_state(row_index, "working")
                self.set_status(
                    f"الحساب {row_index + 1}: لم يصبح Ready خلال دقيقة ونصف - "
                    "إغلاق الصفحة وفتح صفحة جديدة..."
                )

                ConquerMemoryReader.terminate_conquer_pid(pid)
                self.active_sessions.pop(row_index, None)
                time.sleep(1.0)

                result, page_name = self.run_account(
                    path=path,
                    username=username,
                    password=password,
                    account_number=row_index + 1,
                    total_accounts=len(self.accounts_data),
                )

                if result == "SUCCESS":
                    if 0 <= row_index < len(self.accounts_data):
                        self.accounts_data[row_index]["character_name"] = page_name or ""
                        self.account_manager.save_accounts(self.accounts_data)

                    self.set_row_state(row_index, "success", page_name or "")
                    self.set_status(
                        f"الحساب {row_index + 1}: تم فتح صفحة جديدة وأصبح Ready"
                    )
                    return True

                if result == "RESTART_ALL_ACCOUNTS":
                    if not self._timer_stop_requested():
                        self.is_running = True
                        self.run_in_thread(self.process_accounts)
                    return True

                self.set_row_state(row_index, "error")
                self.set_status(
                    f"الحساب {row_index + 1}: فشل فتح الصفحة الجديدة - {result}"
                )
                return False

            if pid not in ConquerMemoryReader.list_conquer_pids():
                return reopen_same_account("PID_MISSING")

            if self.window_disconnect_detector.has_disconnect_dialog(pid):
                print(
                    f"Background disconnect detected - account {row_index + 1} - PID {pid}"
                )
                self.set_status(
                    f"الحساب {row_index + 1}: Disconnected - جاري إعادة الدخول..."
                )
                self.window_disconnect_detector.press_ok(pid)
                time.sleep(0.5)

            self.window_disconnect_detector.activate_main_window(pid)
            time.sleep(0.3)

            self.set_row_state(row_index, "working")
            self.set_status(
                f"الحساب {row_index + 1} حالته غير سليمة - جاري تسجيل الدخول من جديد..."
            )

            while (
                time.time() < recovery_deadline
                and not self.pause_requested
                and not self.monitor_pause_event.is_set()
            ):
                if pid not in ConquerMemoryReader.list_conquer_pids():
                    return reopen_same_account("PID_DISAPPEARED")

                self.window_disconnect_detector.activate_main_window(pid)
                time.sleep(0.2)

                entered = self.login_task.start(
                    username=username,
                    password=password,
                    target_pid=pid,
                )

                if entered:
                    if self.pause_requested or self.monitor_pause_event.is_set():
                        return

                    if self.login_button_task.start(target_pid=pid):
                        message_type = self.post_login_task.wait_for_message(timeout=6.0)

                        if self._handle_global_login_condition(message_type):
                            return

                        if message_type == PostLoginMessageTask.DISCONNECTED:
                            self.post_login_task.press_ok()
                            time.sleep(0.7)
                            self.login_button_task.start(target_pid=pid)

                        elif message_type == PostLoginMessageTask.WRONG_PASSWORD:
                            self.set_status(
                                f"الحساب {row_index + 1}: Wrong password أثناء Recovery - إعادة كتابة الباسورد..."
                            )
                            print(
                                f"Recovery wrong password detected - account {row_index + 1} - "
                                f"PID {pid}; pressing OK and rewriting password"
                            )
                            self.post_login_task.press_ok()
                            time.sleep(0.5)
                            if self.login_task.rewrite_password(
                                password,
                                target_pid=pid,
                            ):
                                if self.login_button_task.start(target_pid=pid):
                                    second_message = self.post_login_task.wait_for_message(timeout=6.0)

                                    if self._handle_global_login_condition(second_message):
                                        return

                                    if second_message == PostLoginMessageTask.WRONG_PASSWORD:
                                        print(
                                            f"Recovery wrong password repeated after rewrite - "
                                            f"account {row_index + 1} - PID {pid}; restarting all pages"
                                        )
                                        self.post_login_task.press_ok()
                                        self._restart_all_accounts_after_password_error(
                                            row_index + 1,
                                            "RECOVERY_WRONG_PASSWORD_AFTER_REWRITE",
                                        )
                                        if not self._timer_stop_requested():
                                            self.is_running = True
                                            self.run_in_thread(self.process_accounts)
                                        return

                                    if second_message == PostLoginMessageTask.DISCONNECTED:
                                        self.post_login_task.press_ok()
                                        time.sleep(0.7)
                                        self.login_button_task.start(target_pid=pid)

                while (
                    time.time() < recovery_deadline
                    and not self.pause_requested
                    and not self.monitor_pause_event.is_set()
                ):
                    if pid not in ConquerMemoryReader.list_conquer_pids():
                        return reopen_same_account("PID_DISAPPEARED")

                    if self.post_login_task.is_server_crowded():
                        remaining = max(0, int(recovery_deadline - time.time()))
                        print(
                            f"Recovery crowded - account {row_index + 1} - PID {pid} - "
                            f"retry Log In after 10s - {remaining}s left"
                        )
                        self.set_status(
                            f"الحساب {row_index + 1}: السيرفر مزدحم - "
                            "إعادة Log In بعد 10 ثواني..."
                        )
                        time.sleep(min(10.0, max(0.0, recovery_deadline - time.time())))
                        if time.time() < recovery_deadline:
                            self.window_disconnect_detector.activate_main_window(pid)
                            time.sleep(0.2)
                            self.login_button_task.start(target_pid=pid)
                        continue

                    current_name, current_state = self._read_health(pid)
                    disconnected = self.window_disconnect_detector.has_disconnect_dialog(pid)

                    print(
                        f"Recovery health - account {row_index + 1} - PID {pid} - "
                        f"Name: {current_name!r} - State: {current_state} - "
                        f"DisconnectDialog: {disconnected}"
                    )

                    if (
                        current_name == expected_name
                        and current_state is not None
                        and not disconnected
                    ):
                        # During recovery, memory name/state alone is not
                        # enough. The exact bug we are fixing is a stale
                        # memory value that still shows the character name
                        # while the same PID is actually back at Login. Only
                        # a live in-window timer is allowed to mark recovery
                        # as successful.
                        timer_result = self.timer_heartbeat_detector.check(
                            pid,
                            stop_check=self._timer_stop_requested,
                        )
                        print(
                            f"Recovery final timer check - account {row_index + 1} - "
                            f"PID {pid} - State {current_state} - {timer_result}"
                        )

                        if timer_result == TimerHeartbeatDetector.ACTIVE:
                            session["page_name"] = current_name or expected_name
                            if not self._state_requires_timer(current_state):
                                session["healthy_state"] = current_state
                            self.active_sessions[row_index] = session
                            self.set_row_state(
                                row_index,
                                "success",
                                session["page_name"],
                            )
                            self.set_status(
                                f"الحساب {row_index + 1}: رجع Ready - العداد شغال داخل نفس الصفحة"
                            )
                            return True

                        self._mark_state_timer_gated(
                            current_state,
                            row_index,
                            pid,
                            f"RECOVERY_TIMER_{timer_result}",
                        )
                        print(
                            f"Recovery health ignored - account {row_index + 1} - "
                            f"PID {pid} - memory looks ready but timer is {timer_result}"
                        )

                    # If the login form is visible again, go back and type
                    # the credentials again instead of waiting passively.
                    if self.login_task.find_login_fields(target_pid=pid, verbose=False):
                        break

                    time.sleep(2.0)

                if not entered:
                    time.sleep(0.5)

            if self.pause_requested or self.monitor_pause_event.is_set():
                return

            return reopen_same_account("NOT_READY_90_SECONDS")

    finally:
        self._mark_recovery_finished(row_index)


def apply_password_error_policy_patch():
    HealthAwareLauncher._recover_logged_out_account = _recover_logged_out_account


apply_password_error_policy_patch()
