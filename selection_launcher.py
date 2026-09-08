import time
import customtkinter as ctk

from clear_all_launcher import ClearAllAwareLauncher
from tasks.memory_reader import ConquerMemoryReader


class SelectionAwareLauncher(ClearAllAwareLauncher):
    """Adds per-account checkboxes and incremental selected-account starting."""

    def __init__(self):
        self.selected_run_only = True
        self.pending_start_indices = []
        super().__init__()

        # Start is incremental now: it opens only selected accounts that do not
        # already have a live registered Conquer page.
        self.start_fresh_button.configure(text="Start")

        controls = self.resume_button.master

        self.select_all_button = ctk.CTkButton(
            controls,
            text="تحديد الكل",
            width=105,
            height=40,
            command=self.select_all_accounts,
        )
        self.select_all_button.pack(side="right", padx=6, pady=10)

        self.clear_selection_button = ctk.CTkButton(
            controls,
            text="إلغاء التحديد",
            width=115,
            height=40,
            command=self.clear_account_selection,
        )
        self.clear_selection_button.pack(side="right", padx=6, pady=10)

    def create_account_row(self, account=None):
        super().create_account_row(account)

        row = self.account_rows[-1]

        # Shift the existing row one column right and put the selection box first.
        for key in ("number", "username", "password", "name", "lamp", "delete"):
            widget = row[key]
            info = widget.grid_info()
            widget.grid_configure(column=int(info.get("column", 0)) + 1)

        selected_var = ctk.BooleanVar(value=True)
        selected_box = ctk.CTkCheckBox(
            row["frame"],
            text="",
            width=28,
            variable=selected_var,
            onvalue=True,
            offvalue=False,
        )
        selected_box.grid(row=0, column=0, padx=(6, 0), pady=7)

        row["selected_var"] = selected_var
        row["selected_box"] = selected_box

    def select_all_accounts(self):
        for row in self.account_rows:
            var = row.get("selected_var")
            if var is not None:
                var.set(True)
        self.set_status("تم تحديد كل الحسابات")

    def clear_account_selection(self):
        for row in self.account_rows:
            var = row.get("selected_var")
            if var is not None:
                var.set(False)
        self.set_status("تم إلغاء تحديد كل الحسابات")

    def _is_account_selected(self, index):
        if not (0 <= index < len(self.account_rows)):
            return False
        var = self.account_rows[index].get("selected_var")
        return bool(var.get()) if var is not None else True

    def _selected_indices(self):
        return [
            index
            for index in range(len(self.account_rows))
            if self._is_account_selected(index)
        ]

    def _account_has_live_session(self, index, live_pids=None):
        session = self.active_sessions.get(index)
        if not session:
            return False

        pid = session.get("pid")
        if not pid:
            return False

        if live_pids is None:
            live_pids = set(ConquerMemoryReader.list_conquer_pids())

        return pid in live_pids

    def _account_is_recovering(self, index):
        try:
            with self.recovering_accounts_lock:
                return index in self.recovering_accounts
        except Exception:
            return False

    def _build_incremental_start_queue(self):
        selected = self._selected_indices()
        live_pids = set(ConquerMemoryReader.list_conquer_pids())
        pending = []

        for index in selected:
            if self._account_has_live_session(index, live_pids):
                # Already running: keep it exactly as it is.
                self.set_row_state(index, "success")
                continue

            if self._account_is_recovering(index):
                # A background recovery already owns this account, so do not
                # create a second page for it.
                continue

            pending.append(index)

        return selected, pending

    def start_from_beginning(self):
        """Start only newly selected accounts; never restart live selected ones."""
        if self.is_running:
            self.set_status("يوجد تشغيل جاري بالفعل")
            return

        if not self.save_accounts_from_ui():
            return

        selected, pending = self._build_incremental_start_queue()

        if not selected:
            self.set_status("حدد حساب واحد على الأقل قبل التشغيل")
            return

        if not pending:
            self.monitor_pause_event.clear()
            self.pause_requested = False
            self.set_status("كل الحسابات المحددة شغالة بالفعل - مفيش حساب جديد محتاج Start")
            return

        # Do NOT clear active_sessions here. Existing live pages must stay
        # registered and monitored while only the newly selected rows are opened.
        self.pending_start_indices = list(pending)
        self.current_account_index = pending[0]
        self.pause_requested = False
        self.monitor_pause_event.clear()
        self.is_running = True

        print(
            "Incremental Start - selected rows: "
            f"{[i + 1 for i in selected]} - opening only: {[i + 1 for i in pending]}"
        )
        self.set_status(
            f"Start: جاري تشغيل {len(pending)} حساب جديد فقط من الحسابات المحددة"
        )
        self.run_in_thread(self.process_accounts)

    def resume_processing(self):
        self.monitor_pause_event.clear()
        self.pause_requested = False

        if self.is_running:
            self.set_status("يوجد تشغيل جاري بالفعل")
            return

        if self.pending_start_indices:
            self.is_running = True
            self.run_in_thread(self.process_accounts)
            return

        # Nothing was paused mid-start. Treat Resume as monitor resume only.
        self.set_status("تم استكمال مراقبة الحسابات المفتوحة")

    def process_accounts(self):
        path = self.path_entry.get().strip()
        accounts = list(self.accounts_data)
        total_accounts = len(accounts)

        if not path:
            self.set_status("لم يتم اختيار play.exe")
            self.is_running = False
            return

        # A maintenance/update restart may call us without a prepared queue.
        if not self.pending_start_indices:
            _, pending = self._build_incremental_start_queue()
            self.pending_start_indices = list(pending)

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
                self.set_status(
                    f"متوقف مؤقتًا - الحساب التالي المحدد رقم {next_index + 1}"
                )
                return

            index = self.pending_start_indices[0]
            self.current_account_index = index

            # The user may untick a row after pressing Start. Do not open it.
            if not self._is_account_selected(index):
                self.pending_start_indices.pop(0)
                continue

            live_pids = set(ConquerMemoryReader.list_conquer_pids())
            if self._account_has_live_session(index, live_pids):
                # It may have recovered/opened while waiting in this queue.
                self.set_row_state(index, "success")
                self.pending_start_indices.pop(0)
                continue

            if self._account_is_recovering(index):
                # Leave recovery in charge and skip duplicate opening.
                self.pending_start_indices.pop(0)
                continue

            if not (0 <= index < len(accounts)):
                self.pending_start_indices.pop(0)
                continue

            account = accounts[index]
            self.set_row_state(index, "working")

            result, page_name = self.run_account(
                path=path,
                username=account["username"],
                password=account["password"],
                account_number=index + 1,
                total_accounts=total_accounts,
            )

            if result == "PAGE_TIMEOUT_RETRY":
                self.set_row_state(index, "working")
                self.set_status(
                    f"الحساب {index + 1}: إعادة المحاولة بصفحة جديدة..."
                )
                # Keep the same account at the front of the queue.
                continue

            if result == "SERVER_MAINTENANCE":
                self.set_status("تم اكتشاف صيانة السيرفر - جاري إغلاق كل صفحات Conquer...")
                ConquerMemoryReader.terminate_all_conquer()
                self.active_sessions.clear()
                self.reset_all_row_states()

                if not self._wait_maintenance_retry():
                    self.is_running = False
                    self.set_status("متوقف مؤقتًا أثناء انتظار صيانة السيرفر")
                    return

                # All pages were closed globally, so every currently selected
                # account needs to be opened again.
                self.pending_start_indices = list(self._selected_indices())
                requested_total = len(self.pending_start_indices)
                completed = 0
                continue

            if result == "CLIENT_UPDATE":
                self.set_status("تم اكتشاف Update - جاري إغلاق كل صفحات Conquer وإعادة الفتح...")
                ConquerMemoryReader.terminate_all_conquer()
                self.active_sessions.clear()
                self.reset_all_row_states()

                if not self._wait_update_retry():
                    self.is_running = False
                    self.set_status("متوقف مؤقتًا أثناء انتظار الـ Update")
                    return

                self.pending_start_indices = list(self._selected_indices())
                requested_total = len(self.pending_start_indices)
                completed = 0
                continue

            if result != "SUCCESS":
                self.set_row_state(index, "error", page_name or "")
                self.is_running = False
                self.set_status(f"الحساب {index + 1}: فشل - {result}")
                return

            self.set_row_state(index, "success", page_name)
            accounts[index]["character_name"] = page_name
            self.accounts_data = accounts
            self.account_manager.save_accounts(accounts)

            self.pending_start_indices.pop(0)
            completed += 1

            if self.pause_requested:
                self.is_running = False
                self.set_status("متوقف مؤقتًا")
                return

            self.set_status(
                f"Start: تم تشغيل {completed}/{requested_total} حساب جديد - {page_name}"
            )
            time.sleep(1.0)

        self.current_account_index = len(accounts)
        self.is_running = False
        self.set_status(f"Start تم - اتشغل {completed} حساب جديد، والصفحات القديمة فضلت شغالة")
