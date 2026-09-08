import time

from control_launcher import ControlAwareLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask
from tasks.window_disconnect_detector import WindowDisconnectDetector
from tasks.timer_heartbeat_detector import TimerHeartbeatDetector


class HealthAwareLauncher(ControlAwareLauncher):
    """Monitor accounts cheaply, then visually confirm only suspicious pages.

    Memory state values are learned dynamically. If the same value is observed
    in both a normal gameplay context and a non-gameplay/login context, that
    value becomes timer-gated for the rest of the run. No numeric state is
    hard-coded as special.
    """

    def __init__(self):
        self.window_disconnect_detector = WindowDisconnectDetector()
        self.timer_heartbeat_detector = TimerHeartbeatDetector()
        self.timer_gated_states = set()
        super().__init__()

    def _read_health(self, pid):
        if not pid or pid not in ConquerMemoryReader.list_conquer_pids():
            return None, None

        reader = None
        try:
            reader = ConquerMemoryReader(pid)
            return reader.read_name() or "", reader.read_state()
        except Exception as error:
            print(f"Health read failed for PID {pid}: {error}")
            return None, None
        finally:
            if reader is not None:
                reader.close()

    def _state_requires_timer(self, state):
        return state is not None and state in self.timer_gated_states

    def _mark_state_timer_gated(self, state, row_index, pid, reason):
        if state is None:
            return False

        first_time = state not in self.timer_gated_states
        self.timer_gated_states.add(state)

        if first_time:
            print(
                f"Dynamic timer gate learned - account {row_index + 1} - PID {pid} - "
                f"State {state} - Reason: {reason}"
            )
        return first_time

    def _session_is_healthy(self, session, current_name, current_state, disconnected=False):
        expected_name = session.get("page_name", "")
        healthy_state = session.get("healthy_state")

        return (
            not disconnected
            and current_name is not None
            and current_state is not None
            and bool(expected_name)
            and current_name == expected_name
            and healthy_state is not None
            and not self._state_requires_timer(current_state)
            and current_state == healthy_state
        )

    def _refresh_baseline_from_live_page(self, row_index, session):
        pid = session.get("pid")
        current_name, current_state = self._read_health(pid)

        if current_state is None:
            return False

        if self._state_requires_timer(current_state):
            print(
                f"Baseline refresh blocked - account {row_index + 1} - PID {pid} - "
                f"State {current_state} is dynamically timer-gated"
            )
            return False

        page_name = current_name or session.get("page_name", "")

        session["pid"] = pid
        session["page_name"] = page_name
        session["healthy_state"] = current_state
        self.active_sessions[row_index] = session

        if 0 <= row_index < len(self.accounts_data):
            self.accounts_data[row_index]["character_name"] = page_name
            self.account_manager.save_accounts(self.accounts_data)

        self.set_row_state(row_index, "success", page_name)
        self.set_status(
            f"الحساب {row_index + 1}: العداد شغال - تم اعتماد البيانات الحالية كـBaseline جديد"
        )

        print(
            f"Live baseline refreshed - account {row_index + 1} - PID {pid} - "
            f"Name: {page_name!r} - Healthy State: {current_state}"
        )
        return True

    def _timer_stop_requested(self):
        return (
            self.pause_requested
            or self.monitor_pause_event.is_set()
            or self.monitor_stop_event.is_set()
        )

    def _reopen_missing_account(self, row_index, session):
        """Open a brand-new page only for the account whose old PID disappeared."""
        if not self._mark_recovery_started(row_index):
            return

        try:
            if self.is_running or self._timer_stop_requested():
                return

            with self.recovery_lock:
                if self.is_running or self._timer_stop_requested():
                    return

                username = session.get("username", "")
                password = session.get("password", "")
                path = self.path_entry.get().strip()

                if not username or not password or not path:
                    self.set_row_state(row_index, "error")
                    self.set_status(
                        f"الحساب {row_index + 1}: بيانات الحساب أو مسار play.exe غير مكتمل"
                    )
                    return

                old_pid = session.get("pid")
                print(
                    f"Missing page detected - account {row_index + 1} - old PID {old_pid} - reopening"
                )

                self.set_row_state(row_index, "working")
                self.set_status(
                    f"الحساب {row_index + 1}: الصفحة اختفت - جاري فتح صفحة جديدة لنفس الحساب..."
                )

                result, page_name = self.run_account(
                    path=path,
                    username=username,
                    password=password,
                    account_number=row_index + 1,
                    total_accounts=len(self.accounts_data),
                )

                if result == "SUCCESS":
                    # run_account already registered the new PID/session. Leave
                    # healthy_state empty so the next monitor pass learns the
                    # fresh value from this newly created page.
                    if 0 <= row_index < len(self.accounts_data):
                        self.accounts_data[row_index]["character_name"] = page_name or ""
                        self.account_manager.save_accounts(self.accounts_data)

                    self.set_row_state(row_index, "success", page_name or "")
                    self.set_status(
                        f"الحساب {row_index + 1}: تم فتح صفحة جديدة وتسجيل الدخول بنجاح"
                    )
                    print(
                        f"Missing page recovery success - account {row_index + 1} - Name: {page_name!r}"
                    )
                    return

                if result == "SERVER_MAINTENANCE":
                    ConquerMemoryReader.terminate_all_conquer()
                    self.active_sessions.clear()
                    self.current_account_index = 0
                    self.reset_all_row_states()

                    if self._wait_maintenance_retry() and not self._timer_stop_requested():
                        self.is_running = True
                        self.run_in_thread(self.process_accounts)
                    return

                if result == "CLIENT_UPDATE":
                    ConquerMemoryReader.terminate_all_conquer()
                    self.active_sessions.clear()
                    self.current_account_index = 0
                    self.reset_all_row_states()

                    if self._wait_update_retry() and not self._timer_stop_requested():
                        self.is_running = True
                        self.run_in_thread(self.process_accounts)
                    return

                self.set_row_state(row_index, "error")
                self.set_status(
                    f"الحساب {row_index + 1}: فشل فتح الصفحة الجديدة - {result}"
                )
                print(
                    f"Missing page recovery failed - account {row_index + 1} - {result}"
                )

        finally:
            self._mark_recovery_finished(row_index)

    def _verify_with_timer_before_recovery(self, row_index, session):
        """Run the heavier screenshot heartbeat only for a suspicious page."""
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
                # This state has already been seen in both healthy and non-gameplay contexts.
                # A live timer proves this exact PID/window is still in active gameplay,
                # so preserve the previous baseline instead of trusting memory alone.
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

        if result != TimerHeartbeatDetector.ACTIVE:
            current_name, current_state = self._read_health(pid)
            if current_state is not None and current_state == session.get("healthy_state"):
                self._mark_state_timer_gated(
                    current_state,
                    row_index,
                    pid,
                    f"TIMER_{result}",
                )

        if result == TimerHeartbeatDetector.MISSING:
            print(
                f"Timer confirmation - account {row_index + 1} - PID {pid} - "
                "timer not present inside this PID window; recovery required"
            )

        if self._timer_stop_requested():
            return

        self._recover_logged_out_account(row_index, session)

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
                                self.post_login_task.press_ok()
                                time.sleep(0.5)
                                if self.login_task.rewrite_password(
                                    password,
                                    target_pid=pid,
                                ):
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
                            if self._state_requires_timer(current_state):
                                timer_result = self.timer_heartbeat_detector.check(
                                    pid,
                                    stop_check=self._timer_stop_requested,
                                )
                                print(
                                    f"Recovery timer gate - account {row_index + 1} - "
                                    f"PID {pid} - State {current_state} - {timer_result}"
                                )
                                if timer_result == TimerHeartbeatDetector.ACTIVE:
                                    session["page_name"] = current_name or expected_name
                                    self.active_sessions[row_index] = session
                                    self.set_row_state(
                                        row_index,
                                        "success",
                                        session["page_name"],
                                    )
                                    self.set_status(
                                        f"الحساب {row_index + 1}: رجع حي - State {current_state} متكرر والعداد شغال"
                                    )
                                    return True
                            else:
                                session["page_name"] = current_name or expected_name
                                session["healthy_state"] = current_state
                                self.active_sessions[row_index] = session
                                self.set_row_state(
                                    row_index,
                                    "success",
                                    session["page_name"],
                                )
                                self.set_status(
                                    f"الحساب {row_index + 1}: رجع Ready - Healthy State = {current_state}"
                                )
                                return True

                        # If the login form is visible again, go back and type
                        # the credentials again instead of waiting passively.
                        if self.login_task.find_login_fields():
                            break

                        time.sleep(2.0)

                    if not entered:
                        time.sleep(0.5)

                if self.pause_requested or self.monitor_pause_event.is_set():
                    return

                return reopen_same_account("NOT_READY_90_SECONDS")

        finally:
            self._mark_recovery_finished(row_index)

    def monitor_active_sessions(self):
        """Cheap checks every 10 seconds; timer screenshot only on suspicion."""
        while not self.monitor_stop_event.is_set():
            if self.monitor_pause_event.is_set():
                self.monitor_stop_event.wait(0.25)
                continue

            sessions = list(self.active_sessions.items())
            live_pids = set(ConquerMemoryReader.list_conquer_pids())

            for row_index, session in sessions:
                if self.monitor_pause_event.is_set() or self.monitor_stop_event.is_set():
                    break

                pid = session.get("pid")

                # Missing process/page is definitive. Do not waste time on the
                # visual heartbeat; open a fresh page for this account only.
                if not pid or pid not in live_pids:
                    print(
                        f"Health monitor - account {row_index + 1} - PID {pid} - MISSING PAGE"
                    )
                    self.set_row_state(row_index, "error")

                    if not self.is_running:
                        self.run_in_thread(
                            lambda idx=row_index, sess=dict(session):
                                self._reopen_missing_account(idx, sess)
                        )
                    continue

                current_name, current_state = self._read_health(pid)
                disconnected = self.window_disconnect_detector.has_disconnect_dialog(pid)

                if session.get("healthy_state") is None and current_state is not None:
                    if self._state_requires_timer(current_state):
                        print(
                            f"Health baseline blocked - account {row_index + 1} - "
                            f"PID {pid} - State {current_state} requires timer verification"
                        )
                    else:
                        session["healthy_state"] = current_state
                        self.active_sessions[row_index] = session
                        print(
                            f"Health baseline learned - account {row_index + 1} - "
                            f"PID {pid} - Name: {session.get('page_name')!r} - "
                            f"Healthy State: {current_state}"
                        )

                # Dynamic ambiguity discovery: a memory value may remain identical
                # after logout. Probe only this PID window for the login panel. If the
                # login panel is visible while memory still equals the learned healthy
                # value, this numeric state is ambiguous and must use the timer gate
                # from now on.
                login_page_visible = False
                if (
                    not disconnected
                    and current_state is not None
                    and current_state == session.get("healthy_state")
                    and current_name == session.get("page_name")
                ):
                    login_page_visible = bool(
                        self.login_task.find_login_fields(
                            target_pid=pid,
                            verbose=False,
                        )
                    )
                    if login_page_visible:
                        self._mark_state_timer_gated(
                            current_state,
                            row_index,
                            pid,
                            "LOGIN_PAGE_WITH_SAME_MEMORY_STATE",
                        )

                healthy = self._session_is_healthy(
                    session,
                    current_name,
                    current_state,
                    disconnected=disconnected,
                )

                print(
                    f"Health monitor - account {row_index + 1} - PID {pid} - "
                    f"Name: {current_name!r}/{session.get('page_name')!r} - "
                    f"State: {current_state}/{session.get('healthy_state')} - "
                    f"DisconnectDialog: {disconnected} - "
                    f"{'HEALTHY' if healthy else 'UNHEALTHY'}"
                )

                if healthy:
                    self.set_row_state(row_index, "success")
                    continue

                if login_page_visible:
                    print(
                        f"Health collision - account {row_index + 1} - PID {pid} - "
                        f"State {current_state} matches healthy baseline but login page is visible; "
                        "timer verification required"
                    )

                self.set_row_state(row_index, "error")

                if self.is_running:
                    continue

                if disconnected:
                    self.run_in_thread(
                        lambda idx=row_index, sess=dict(session):
                            self._recover_logged_out_account(idx, sess)
                    )
                else:
                    self.run_in_thread(
                        lambda idx=row_index, sess=dict(session):
                            self._verify_with_timer_before_recovery(idx, sess)
                    )

            for _ in range(40):
                if self.monitor_stop_event.is_set() or self.monitor_pause_event.is_set():
                    break
                self.monitor_stop_event.wait(0.25)
