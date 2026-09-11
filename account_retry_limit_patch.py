"""Skip bad accounts after a small number of failed open/login attempts.

This patch intentionally does not change Login typing/detection internals.
It only controls the account queue:
- each selected account gets up to login_account_max_open_attempts tries
- normal recoverable failures retry the same row
- after the limit, the row is skipped for the current run and the queue moves on
- global stop key 9 still exits immediately
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.memory_reader import ConquerMemoryReader


DEFAULT_RUNTIME_SETTINGS.setdefault("login_account_max_open_attempts", 3)

USER_STOP_RESULTS = {"USER_STOPPED", "STOP_REQUESTED"}
GLOBAL_RESTART_RESULTS = {"SERVER_MAINTENANCE", "CLIENT_UPDATE", "RESTART_ALL_ACCOUNTS"}


def _login_retry_limit(self):
    try:
        value = self.get_runtime_setting("login_account_max_open_attempts", 3)
    except Exception:
        value = 3
    try:
        value = int(float(value))
    except Exception:
        value = 3
    return max(1, min(10, value))


def _remove_pending_index(self, index):
    try:
        self.pending_start_indices = [i for i in self.pending_start_indices if i != index]
    except Exception:
        pass


def _skip_account_current_run(self, index, reason, attempts):
    skipped = getattr(self, "skipped_start_indices", None)
    if skipped is None:
        skipped = set()
        self.skipped_start_indices = skipped
    skipped.add(index)

    _remove_pending_index(self, index)

    try:
        row = self.account_rows[index]
        selected_var = row.get("selected_var")
        if selected_var is not None:
            selected_var.set(False)
    except Exception:
        pass

    try:
        self.set_row_state(index, "error")
    except Exception:
        pass

    print(
        "Account skipped after repeated open/login failures - "
        f"account={index + 1} - attempts={attempts} - last_result={reason}"
    )
    self.set_status(
        f"الحساب {index + 1}: اتعمله Skip بعد {attempts} محاولات فاشلة - راجعه بعدين"
    )


def _reset_start_retry_counter(self, index):
    counters = getattr(self, "start_retry_counts", None)
    if isinstance(counters, dict):
        counters.pop(index, None)


def _record_start_failure(self, index, result):
    counters = getattr(self, "start_retry_counts", None)
    if counters is None:
        counters = {}
        self.start_retry_counts = counters

    attempts = int(counters.get(index, 0)) + 1
    counters[index] = attempts
    max_attempts = _login_retry_limit(self)

    if attempts >= max_attempts:
        _skip_account_current_run(self, index, result, attempts)
        return "SKIPPED"

    print(
        "Account open/login retry scheduled - "
        f"account={index + 1} - attempt={attempts}/{max_attempts} - result={result}"
    )
    self.set_status(
        f"الحساب {index + 1}: محاولة فاشلة {attempts}/{max_attempts} - إعادة المحاولة"
    )
    return "RETRY"


def _selected_not_skipped(self):
    skipped = getattr(self, "skipped_start_indices", set()) or set()
    if hasattr(self, "_selected_indices"):
        try:
            return [i for i in self._selected_indices() if i not in skipped]
        except Exception:
            pass
    return [i for i in range(len(self.account_rows)) if i not in skipped]


def _process_accounts_with_retry_limit(self):
    """SelectionAwareLauncher.process_accounts replacement with retry cap.

    It keeps the same incremental-start behavior, but it no longer lets one bad
    username/password/page block every account behind it forever.
    """
    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        try:
            runner.pause_for_login_priority("process_accounts_start")
        except Exception:
            pass

    monitor_was_paused = False
    try:
        monitor_was_paused = self.monitor_pause_event.is_set()
        if not monitor_was_paused:
            self.monitor_pause_event.set()
            print("Health monitor paused during Start/Login input sequence")
    except Exception:
        monitor_was_paused = True

    try:
        return _process_accounts_core(self)
    finally:
        try:
            if not monitor_was_paused and not self.pause_requested:
                self.monitor_pause_event.clear()
                print("Health monitor resumed after Start/Login input sequence")
        except Exception:
            pass

        runner = getattr(self, "post_login_runner", None)
        if runner is not None:
            try:
                self.app.after(
                    700,
                    lambda: runner.start_if_ready("process_accounts_finished"),
                )
            except Exception as error:
                print(f"Could not schedule post-login command start: {error}")


def _process_accounts_core(self):
    path = self.path_entry.get().strip()
    accounts = list(self.accounts_data)
    total_accounts = len(accounts)

    if not path:
        self.set_status("لم يتم اختيار play.exe")
        self.is_running = False
        return

    if not hasattr(self, "start_retry_counts"):
        self.start_retry_counts = {}
    if not hasattr(self, "skipped_start_indices"):
        self.skipped_start_indices = set()

    # A maintenance/update restart may call us without a prepared queue.
    if not getattr(self, "pending_start_indices", None):
        try:
            _, pending = self._build_incremental_start_queue()
        except Exception:
            pending = _selected_not_skipped(self)
        self.pending_start_indices = [i for i in pending if i not in self.skipped_start_indices]

    if not self.pending_start_indices:
        self.is_running = False
        self.set_status("لا توجد حسابات جديدة محددة تحتاج تشغيل")
        return

    requested_total = len(self.pending_start_indices)
    completed = 0

    while self.pending_start_indices:
        if self.pause_requested:
            self.is_running = False
            next_index = self.pending_start_indices[0]
            self.current_account_index = next_index
            self.set_status(f"متوقف مؤقتًا - الحساب التالي المحدد رقم {next_index + 1}")
            return

        index = self.pending_start_indices[0]
        self.current_account_index = index

        if index in self.skipped_start_indices:
            self.pending_start_indices.pop(0)
            continue

        if not self._is_account_selected(index):
            self.pending_start_indices.pop(0)
            continue

        live_pids = set(ConquerMemoryReader.list_conquer_pids())
        if self._account_has_live_session(index, live_pids):
            self.set_row_state(index, "success")
            self.pending_start_indices.pop(0)
            _reset_start_retry_counter(self, index)
            continue

        if self._account_is_recovering(index):
            self.pending_start_indices.pop(0)
            continue

        if not (0 <= index < len(accounts)):
            self.pending_start_indices.pop(0)
            continue

        account = accounts[index]
        self.set_row_state(index, "working")

        attempt_number = int(self.start_retry_counts.get(index, 0)) + 1
        max_attempts = _login_retry_limit(self)
        print(
            "Account open/login attempt - "
            f"account={index + 1} - attempt={attempt_number}/{max_attempts} - "
            f"username={account.get('username', '')!r}"
        )

        result, page_name = self.run_account(
            path=path,
            username=account["username"],
            password=account["password"],
            account_number=index + 1,
            total_accounts=total_accounts,
        )

        if result in USER_STOP_RESULTS:
            self.is_running = False
            self.set_status("تم الإيقاف الفوري بزر 9")
            print(f"Start/Login stopped by user - account={index + 1}")
            return

        if result == "SERVER_MAINTENANCE":
            self.set_status("تم اكتشاف صيانة السيرفر - جاري إغلاق كل صفحات Conquer...")
            ConquerMemoryReader.terminate_all_conquer()
            self.active_sessions.clear()
            self.reset_all_row_states()
            self.pending_start_indices = _selected_not_skipped(self)
            requested_total = len(self.pending_start_indices)
            completed = 0

            if not self._wait_maintenance_retry():
                self.is_running = False
                self.set_status("متوقف مؤقتًا أثناء انتظار صيانة السيرفر")
                return
            continue

        if result == "CLIENT_UPDATE":
            self.set_status("تم اكتشاف Update - جاري إغلاق كل صفحات Conquer وإعادة الفتح...")
            ConquerMemoryReader.terminate_all_conquer()
            self.active_sessions.clear()
            self.reset_all_row_states()
            self.pending_start_indices = _selected_not_skipped(self)
            requested_total = len(self.pending_start_indices)
            completed = 0

            if not self._wait_update_retry():
                self.is_running = False
                self.set_status("متوقف مؤقتًا أثناء انتظار الـ Update")
                return
            continue

        if result == "RESTART_ALL_ACCOUNTS":
            self.set_status("تم إغلاق كل الصفحات - إعادة تشغيل الحسابات غير المتخطية فقط")
            self.pending_start_indices = _selected_not_skipped(self)
            requested_total = len(self.pending_start_indices)
            completed = 0
            continue

        if result != "SUCCESS":
            if index not in self.pending_start_indices:
                continue

            decision = _record_start_failure(self, index, result)
            if decision == "SKIPPED":
                continue

            # Keep the same account at the front of the queue until its limit.
            continue

        _reset_start_retry_counter(self, index)
        self.set_row_state(index, "success", page_name)
        accounts[index]["character_name"] = page_name
        self.accounts_data = accounts
        self.account_manager.save_accounts(accounts)

        if self.pending_start_indices and self.pending_start_indices[0] == index:
            self.pending_start_indices.pop(0)
        else:
            _remove_pending_index(self, index)

        completed += 1

        if self.pause_requested:
            self.is_running = False
            self.set_status("متوقف مؤقتًا")
            return

        self.set_status(f"Start: تم تشغيل {completed}/{requested_total} حساب جديد - {page_name}")
        time.sleep(1.0)

    self.current_account_index = len(accounts)
    self.is_running = False
    self.set_status(f"Start تم - اتشغل {completed} حساب جديد، واللي فشل 3 مرات اتعمله Skip")


SelectionAwareLauncher.process_accounts = _process_accounts_with_retry_limit

print("Account retry limit patch active: bad accounts skip after 3 failed open/login attempts")
