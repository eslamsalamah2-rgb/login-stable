import time
import customtkinter as ctk

from maintenance_launcher import MaintenanceAwareLauncher
from selection_launcher import SelectionAwareLauncher
from tasks.memory_reader import ConquerMemoryReader

_ORIG_SELECTION_INIT = SelectionAwareLauncher.__init__

SETTING_LABELS = {
    "start_game_threshold": "دقة صورة Start Game",
    "login_fields_threshold": "دقة صورة Username/Password",
    "login_fields_near_threshold": "قبول قريب لحقول Login",
    "post_login_threshold": "دقة رسائل ما بعد Log In",
    "ok_threshold": "دقة زر OK",
    "timer_anchor_threshold": "دقة Anchor العداد/FPS",
    "start_game_timeout": "وقت البحث عن Start Game / ثانية",
    "new_pid_timeout": "وقت انتظار صفحة Conquer الجديدة / ثانية",
    "start_game_attempts": "عدد محاولات فتح اللانشر",
}


def _normal_name(self, value):
    return str(value or "").strip().lower()


def _build_open_pages_panel(self):
    try:
        self.status_label.pack_forget()
    except Exception:
        pass

    self.open_pages_panel = ctk.CTkFrame(self.app)
    self.open_pages_panel.pack(fill="x", padx=18, pady=(0, 8))

    top = ctk.CTkFrame(self.open_pages_panel, fg_color="transparent")
    top.pack(fill="x", padx=10, pady=(8, 3))
    ctk.CTkLabel(
        top,
        text="الصفحات المفتوحة غير المسجلة / الجانبية",
        font=("Segoe UI", 13, "bold"),
        anchor="w",
    ).pack(side="left")
    self.open_pages_summary_label = ctk.CTkLabel(top, text="لم يتم الفحص بعد")
    self.open_pages_summary_label.pack(side="right")

    self.open_pages_text = ctk.CTkTextbox(
        self.open_pages_panel,
        height=72,
        font=("Consolas", 12),
    )
    self.open_pages_text.pack(fill="x", padx=10, pady=(0, 8))
    self.open_pages_text.insert(
        "1.0",
        "اضغط Scan Open لربط الصفحات الموجودة بالحسابات أو عرض غير المعروف هنا.",
    )
    self.open_pages_text.configure(state="disabled")
    self.status_label.pack(fill="x", padx=25, pady=(0, 14))


def _set_open_pages_panel(self, unknown_pages, attached_count=0, already_count=0):
    self.unknown_open_pages = list(unknown_pages or [])

    def apply_update():
        if not hasattr(self, "open_pages_text"):
            return
        self.open_pages_text.configure(state="normal")
        self.open_pages_text.delete("1.0", "end")
        if not self.unknown_open_pages:
            text = "لا توجد صفحات جانبية غير مسجلة. كل الصفحات المعروفة اتربطت أو لا توجد صفحات مفتوحة."
        else:
            text = "\n".join(
                f"PID {p.get('pid')} | Name={p.get('name')!r} | State={p.get('state')} | Reason={p.get('reason')}"
                for p in self.unknown_open_pages
            )
        self.open_pages_text.insert("1.0", text)
        self.open_pages_text.configure(state="disabled")
        self.open_pages_summary_label.configure(
            text=f"اتربط: {attached_count} | موجود مسبقًا: {already_count} | جانبي: {len(self.unknown_open_pages)}"
        )

    self.app.after(0, apply_update)


def _scan_existing_open_pages(self):
    if self.is_running:
        self.set_status("لا يمكن عمل Scan Open أثناء تشغيل الحسابات")
        return
    if not self.save_accounts_from_ui():
        return
    self.set_status("Scan Open - جاري قراءة أسماء الصفحات المفتوحة من Memory...")
    self.run_in_thread(
        lambda: self._scan_existing_open_pages_worker(
            list(self.accounts_data),
            dict(self.active_sessions),
        )
    )


def _scan_existing_open_pages_worker(self, accounts, sessions):
    live_pids = set(ConquerMemoryReader.list_conquer_pids())
    registered_pids = {
        s.get("pid") for s in sessions.values() if s.get("pid") in live_pids
    }

    name_to_rows = {}
    for index, account in enumerate(accounts):
        key = self._normal_name(account.get("character_name", ""))
        if key:
            name_to_rows.setdefault(key, []).append(index)

    used_rows = {
        row for row, session in sessions.items() if session.get("pid") in live_pids
    }
    unknown_pages = []
    attached_count = 0
    already_count = 0

    for pid in sorted(live_pids):
        if pid in registered_pids:
            already_count += 1
            continue

        reader = None
        try:
            reader = ConquerMemoryReader(pid)
            name = reader.read_name() or ""
            state = reader.read_state()
        except Exception as error:
            unknown_pages.append({"pid": pid, "name": "", "state": None, "reason": f"READ_ERROR:{error}"})
            continue
        finally:
            if reader is not None:
                reader.close()

        key = self._normal_name(name)
        if not key:
            unknown_pages.append({"pid": pid, "name": name, "state": state, "reason": "NO_MEMORY_NAME"})
            continue

        matched_row = None
        for candidate in name_to_rows.get(key, []):
            if candidate not in used_rows:
                matched_row = candidate
                break

        if matched_row is None:
            unknown_pages.append({"pid": pid, "name": name, "state": state, "reason": "NOT_IN_SAVED_ACCOUNTS_OR_DUPLICATE"})
            continue

        account = accounts[matched_row]
        self.active_sessions[matched_row] = {
            "pid": pid,
            "username": account.get("username", ""),
            "password": account.get("password", ""),
            "page_name": name,
            "healthy_state": None,
        }
        used_rows.add(matched_row)
        attached_count += 1
        self.set_row_state(matched_row, "success", name)
        print(f"Existing open page attached - account {matched_row + 1} - PID {pid} - Name: {name!r} - State: {state}")

    self._set_open_pages_panel(unknown_pages, attached_count, already_count)
    self.set_status(
        f"Scan Open تم - اتربط {attached_count} صفحة، موجود مسبقًا {already_count}، جانبي {len(unknown_pages)}"
    )


def _open_settings_window(self):
    window = ctk.CTkToplevel(self.app)
    window.title("Settings")
    window.geometry("520x560")
    window.transient(self.app)
    window.grab_set()
    ctk.CTkLabel(window, text="إعدادات قابلة للتعديل", font=("Segoe UI", 20, "bold")).pack(pady=(15, 8))
    body = ctk.CTkScrollableFrame(window, height=420)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    entries = {}
    for key, label_text in SETTING_LABELS.items():
        row = ctk.CTkFrame(body)
        row.pack(fill="x", padx=6, pady=5)
        ctk.CTkLabel(row, text=label_text, width=290, anchor="w").pack(side="left", padx=(8, 4), pady=7)
        entry = ctk.CTkEntry(row, width=130)
        entry.pack(side="right", padx=(4, 8), pady=7)
        entry.insert(0, str(self.runtime_settings.get(key, self.get_runtime_setting(key))))
        entries[key] = entry

    def save_window_settings():
        changed = {
            key: self._coerce_runtime_setting(key, entry.get())
            for key, entry in entries.items()
        }
        self.runtime_settings.update(changed)
        self.apply_runtime_settings()
        self.save_settings()
        print(f"Runtime settings updated: {changed}")
        self.set_status("تم حفظ الإعدادات وتطبيقها")
        window.destroy()

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=16, pady=(0, 14))
    ctk.CTkButton(buttons, text="حفظ", height=38, command=save_window_settings).pack(side="right", padx=6)
    ctk.CTkButton(buttons, text="إلغاء", height=38, command=window.destroy).pack(side="right", padx=6)


def _selection_init_with_scan_and_settings(self):
    self.unknown_open_pages = []
    _ORIG_SELECTION_INIT(self)
    controls = self.resume_button.master

    self.scan_open_pages_button = ctk.CTkButton(
        controls,
        text="Scan Open",
        width=110,
        height=40,
        command=self.scan_existing_open_pages,
    )
    self.scan_open_pages_button.pack(side="right", padx=6, pady=10)

    self.settings_button = ctk.CTkButton(
        controls,
        text="Settings",
        width=105,
        height=40,
        command=self.open_settings_window,
    )
    self.settings_button.pack(side="right", padx=6, pady=10)

    self._build_open_pages_panel()
    self.app.after(900, self.scan_existing_open_pages)


def _open_conquer_pid_with_settings(self, path, account_number, total_accounts):
    max_attempts = int(self.get_runtime_setting("start_game_attempts", 3))
    start_timeout = float(self.get_runtime_setting("start_game_timeout", 20.0))
    pid_timeout = float(self.get_runtime_setting("new_pid_timeout", 20.0))

    for attempt in range(1, max_attempts + 1):
        previous_conquer_pids = ConquerMemoryReader.list_conquer_pids()
        self.set_status(f"الحساب {account_number}/{total_accounts}: فتح اللانشر محاولة {attempt}/{max_attempts}...")
        success, message = self.launcher.open(path)
        if not success:
            return None, "OPEN_ERROR"

        time.sleep(0.8)
        launcher_pid = self._current_launcher_pid()
        self.set_status(f"الحساب {account_number}/{total_accounts}: البحث عن Start Game محاولة {attempt}/{max_attempts}...")
        if not self.start_game_task.start(target_pid=launcher_pid, timeout=start_timeout):
            print(f"Start Game attempt {attempt}/{max_attempts} failed - button not found")
            self._stop_launcher_only()
            time.sleep(1.0)
            continue

        self.set_status(f"الحساب {account_number}/{total_accounts}: انتظار صفحة Conquer الجديدة محاولة {attempt}/{max_attempts}...")
        conquer_pid = ConquerMemoryReader.wait_for_new_conquer_pid(
            previous_conquer_pids,
            timeout=pid_timeout,
            launcher_pid=launcher_pid,
        )
        if conquer_pid is not None:
            return conquer_pid, "SUCCESS"

        print(f"Start Game attempt {attempt}/{max_attempts} clicked but no new Conquer PID appeared - retrying with a fresh launcher")
        self._stop_launcher_only()
        time.sleep(1.0)

    return None, "CONQUER_PID_ERROR"


def apply_existing_pages_settings_patch():
    SelectionAwareLauncher.__init__ = _selection_init_with_scan_and_settings
    SelectionAwareLauncher._normal_name = _normal_name
    SelectionAwareLauncher._build_open_pages_panel = _build_open_pages_panel
    SelectionAwareLauncher._set_open_pages_panel = _set_open_pages_panel
    SelectionAwareLauncher.scan_existing_open_pages = _scan_existing_open_pages
    SelectionAwareLauncher._scan_existing_open_pages_worker = _scan_existing_open_pages_worker
    SelectionAwareLauncher.open_settings_window = _open_settings_window
    MaintenanceAwareLauncher._open_conquer_pid_with_retries = _open_conquer_pid_with_settings


apply_existing_pages_settings_patch()
