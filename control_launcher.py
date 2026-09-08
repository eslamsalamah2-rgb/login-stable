import threading
import time

from maintenance_launcher import MaintenanceAwareLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask


class ControlAwareLauncher(MaintenanceAwareLauncher):
    """Global pause/resume plus automatic relog for logged-out accounts."""

    def __init__(self):
        self.monitor_pause_event = threading.Event()
        self.recovery_lock = threading.Lock()
        self.recovering_accounts = set()
        self.recovering_accounts_lock = threading.Lock()
        super().__init__()

    def pause_processing(self):
        self.monitor_pause_event.set()
        self.pause_requested = True

        for task in (
            self.start_game_task,
            self.login_task,
            self.login_button_task,
            self.post_login_task,
        ):
            try:
                task.stop()
            except Exception:
                pass

        self.set_status(
            f"إيقاف مؤقت كامل - تم إيقاف التشغيل والـMemory Scan عند الحساب {self.current_account_index + 1}"
        )

    def resume_processing(self):
        self.monitor_pause_event.clear()
        self.pause_requested = False

        if self.is_running:
            self.set_status("تم استكمال الـMemory Scan - عملية الحساب الحالية ما زالت تعمل")
            return

        if not self.save_accounts_from_ui():
            return

        if self.current_account_index >= len(self.accounts_data):
            self.set_status("تم استكمال مراقبة الحسابات المفتوحة")
            return

        self.is_running = True
        self.run_in_thread(self.process_accounts)

    def start_from_beginning(self):
        self.monitor_pause_event.clear()
        super().start_from_beginning()

    def _mark_recovery_started(self, row_index):
        with self.recovering_accounts_lock:
            if row_index in self.recovering_accounts:
                return False
            self.recovering_accounts.add(row_index)
            return True

    def _mark_recovery_finished(self, row_index):
        with self.recovering_accounts_lock:
            self.recovering_accounts.discard(row_index)

    def _handle_global_login_condition(self, message_type):
        if message_type not in {
            PostLoginMessageTask.SERVER_MAINTENANCE,
            PostLoginMessageTask.CLIENT_UPDATE,
        }:
            return False

        self.post_login_task.press_ok()
        ConquerMemoryReader.terminate_all_conquer()
        self.active_sessions.clear()
        self.current_account_index = 0
        self.reset_all_row_states()

        if message_type == PostLoginMessageTask.SERVER_MAINTENANCE:
            self.set_status("صيانة السيرفر - تم إغلاق كل الصفحات، المحاولة بعد دقيقة")
            if not self._wait_maintenance_retry():
                return True
        else:
            self.set_status("Client Update - تم إغلاق كل الصفحات، إعادة الفتح بعد 5 ثواني")
            if not self._wait_update_retry():
                return True

        if not self.pause_requested and not self.monitor_pause_event.is_set():
            self.is_running = True
            self.run_in_thread(self.process_accounts)

        return True

    def _recover_logged_out_account(self, row_index, session):
        """Relog the same open Conquer page after STATE_LOGGED_OUT is detected."""
        if not self._mark_recovery_started(row_index):
            return

        try:
            # Do not interfere with the normal account-opening sequence.
            if self.is_running or self.pause_requested or self.monitor_pause_event.is_set():
                return

            with self.recovery_lock:
                if self.pause_requested or self.monitor_pause_event.is_set():
                    return

                pid = session.get("pid")
                username = session.get("username", "")
                password = session.get("password", "")

                if not pid or not username or not password:
                    self.set_row_state(row_index, "error")
                    return

                self.set_row_state(row_index, "working")
                self.set_status(
                    f"الحساب {row_index + 1} عمل Logout - جاري تسجيل الدخول من جديد..."
                )

                # The logged-out page is still open, so we only rewrite the
                # credentials and press Log In. We do not open a new game page.
                if not self.login_task.start(username=username, password=password):
                    if not self.pause_requested:
                        self.set_row_state(row_index, "error")
                        self.set_status(
                            f"الحساب {row_index + 1}: لم أجد خانات تسجيل الدخول لإعادة الدخول"
                        )
                    return

                if self.pause_requested or self.monitor_pause_event.is_set():
                    return

                if not self.login_button_task.start():
                    self.set_row_state(row_index, "error")
                    return

                message_type = self.post_login_task.wait_for_message(timeout=6.0)

                if self._handle_global_login_condition(message_type):
                    return

                if message_type == PostLoginMessageTask.DISCONNECTED:
                    self.post_login_task.press_ok()
                    time.sleep(0.7)
                    if not self.login_button_task.start():
                        self.set_row_state(row_index, "error")
                        return
                    message_type = self.post_login_task.wait_for_message(timeout=6.0)
                    if self._handle_global_login_condition(message_type):
                        return

                if message_type == PostLoginMessageTask.WRONG_PASSWORD:
                    self.post_login_task.press_ok()
                    time.sleep(0.5)
                    if not self.login_task.rewrite_password(password):
                        self.set_row_state(row_index, "error")
                        return
                    if not self.login_button_task.start():
                        self.set_row_state(row_index, "error")
                        return
                    message_type = self.post_login_task.wait_for_message(timeout=6.0)
                    if self._handle_global_login_condition(message_type):
                        return

                    if message_type == PostLoginMessageTask.WRONG_PASSWORD:
                        self.post_login_task.press_ok()
                        self.set_row_state(row_index, "error")
                        self.set_status(
                            f"الحساب {row_index + 1}: الباسورد ما زال مرفوضًا"
                        )
                        return

                # Wait for the exact memory state to return to LOGGED_IN.
                # No short timeout: the server may need time to complete login.
                while not self.pause_requested and not self.monitor_pause_event.is_set():
                    reader = None
                    value = None
                    try:
                        reader = ConquerMemoryReader(pid)
                        value = reader.read_state()
                    except Exception as error:
                        print(
                            f"Relog state check failed for account {row_index + 1}, PID {pid}: {error}"
                        )
                    finally:
                        if reader is not None:
                            reader.close()

                    state_text = ConquerMemoryReader.state_name(value)
                    print(
                        f"Relog monitor - account {row_index + 1} - PID {pid} - "
                        f"Value: {value} - {state_text}"
                    )

                    if value == ConquerMemoryReader.STATE_LOGGED_IN:
                        self.set_row_state(row_index, "success")
                        self.set_status(
                            f"الحساب {row_index + 1}: تم تسجيل الدخول من جديد بنجاح"
                        )
                        return

                    # If the process disappeared, this page cannot be relogged.
                    if pid not in ConquerMemoryReader.list_conquer_pids():
                        self.set_row_state(row_index, "error")
                        self.set_status(
                            f"الحساب {row_index + 1}: صفحة اللعبة اتقفلت"
                        )
                        return

                    time.sleep(2.0)

        finally:
            self._mark_recovery_finished(row_index)

    def monitor_active_sessions(self):
        """Check every successful account every 10 seconds and relog LOGGED_OUT."""
        while not self.monitor_stop_event.is_set():
            if self.monitor_pause_event.is_set():
                self.monitor_stop_event.wait(0.25)
                continue

            sessions = list(self.active_sessions.items())

            for row_index, session in sessions:
                if self.monitor_pause_event.is_set() or self.monitor_stop_event.is_set():
                    break

                pid = session.get("pid")
                if not pid:
                    continue

                reader = None
                value = None

                try:
                    reader = ConquerMemoryReader(pid)
                    value = reader.read_state()
                except Exception as error:
                    print(
                        f"State monitor could not open PID {pid}: {error}"
                    )
                finally:
                    if reader is not None:
                        reader.close()

                state_text = ConquerMemoryReader.state_name(value)

                print(
                    f"State monitor - account {row_index + 1} - PID {pid} - "
                    f"Value: {value} - {state_text}"
                )

                if value == ConquerMemoryReader.STATE_LOGGED_IN:
                    self.set_row_state(row_index, "success")

                elif value == ConquerMemoryReader.STATE_LOGGED_OUT:
                    self.set_row_state(row_index, "error")

                    # If another account is currently being opened, defer the
                    # relog until the next 10-second monitor pass to avoid two
                    # automation flows fighting over mouse/keyboard focus.
                    if not self.is_running:
                        self.run_in_thread(
                            lambda idx=row_index, sess=dict(session):
                                self._recover_logged_out_account(idx, sess)
                        )

                else:
                    self.set_row_state(row_index, "error")

            for _ in range(40):
                if self.monitor_stop_event.is_set() or self.monitor_pause_event.is_set():
                    break
                self.monitor_stop_event.wait(0.25)
