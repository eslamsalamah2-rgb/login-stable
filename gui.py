import customtkinter as ctk
from tkinter import filedialog
import keyboard
import threading
import json
import os
import time

from launcher import Launcher
from account_manager import AccountManager
from tasks.start_game_task import StartGameTask
from tasks.login_task import LoginTask
from tasks.login_button_task import LoginButtonTask
from tasks.post_login_message_task import PostLoginMessageTask
from tasks.memory_reader import ConquerMemoryReader
from config import (
    CONFIG_FILE,
    WINDOW_TITLE,
    START_HOTKEY,
    STOP_HOTKEY
)


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class SimpleLauncher:

    def __init__(self):
        self.app = ctk.CTk()
        self.app.title(WINDOW_TITLE)
        self.app.geometry("1080x720")
        self.app.minsize(950, 620)
        self.app.resizable(True, True)

        self.launcher = Launcher()
        self.account_manager = AccountManager()
        self.start_game_task = StartGameTask()
        self.login_task = LoginTask()
        self.login_button_task = LoginButtonTask()
        self.post_login_task = PostLoginMessageTask()

        self.account_rows = []
        self.accounts_data = []
        self.current_account_index = 0
        self.pause_requested = False
        self.is_running = False

        # Successful pages are registered here by account-row index.
        # The monitor only observes them for now; it does NOT reopen anything.
        self.active_sessions = {}
        self.monitor_stop_event = threading.Event()

        self.build_ui()
        self.load_settings()
        self.load_accounts_into_ui()

        keyboard.add_hotkey(
            START_HOTKEY,
            lambda: self.app.after(0, self.resume_processing)
        )

        keyboard.add_hotkey(
            STOP_HOTKEY,
            lambda: self.app.after(0, self.pause_processing)
        )

        # Permanent background state monitor. It checks registered pages every
        # 10 seconds and changes only their lamps.
        self.run_in_thread(self.monitor_active_sessions)

        self.app.protocol("WM_DELETE_WINDOW", self.close_program)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def build_ui(self):
        title = ctk.CTkLabel(
            self.app,
            text="CONQUER LOGIN MANAGER",
            font=("Segoe UI", 25, "bold")
        )
        title.pack(pady=(18, 10))

        path_frame = ctk.CTkFrame(self.app)
        path_frame.pack(fill="x", padx=18, pady=(0, 10))

        self.path_entry = ctk.CTkEntry(
            path_frame,
            height=38,
            placeholder_text="اختار play.exe"
        )
        self.path_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(10, 8),
            pady=10
        )

        select_button = ctk.CTkButton(
            path_frame,
            text="اختيار الصفحة",
            width=130,
            command=self.select_file
        )
        select_button.pack(side="left", padx=(0, 10), pady=10)

        controls = ctk.CTkFrame(self.app)
        controls.pack(fill="x", padx=18, pady=(0, 10))

        self.start_fresh_button = ctk.CTkButton(
            controls,
            text="ابدأ من الأول",
            width=150,
            height=40,
            command=self.start_from_beginning
        )
        self.start_fresh_button.pack(side="left", padx=(10, 6), pady=10)

        self.pause_button = ctk.CTkButton(
            controls,
            text=f"إيقاف مؤقت  {STOP_HOTKEY}",
            width=160,
            height=40,
            command=self.pause_processing
        )
        self.pause_button.pack(side="left", padx=6, pady=10)

        self.resume_button = ctk.CTkButton(
            controls,
            text=f"استكمال  {START_HOTKEY}",
            width=160,
            height=40,
            command=self.resume_processing
        )
        self.resume_button.pack(side="left", padx=6, pady=10)

        self.add_account_button = ctk.CTkButton(
            controls,
            text="+ إضافة حساب",
            width=140,
            height=40,
            command=self.add_empty_account
        )
        self.add_account_button.pack(side="right", padx=(6, 10), pady=10)

        self.save_accounts_button = ctk.CTkButton(
            controls,
            text="حفظ الحسابات",
            width=130,
            height=40,
            command=self.save_accounts_from_ui
        )
        self.save_accounts_button.pack(side="right", padx=6, pady=10)

        header = ctk.CTkFrame(self.app, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(3, 3))

        headers = [
            ("#", 35),
            ("Username", 210),
            ("Password", 210),
            ("اسم الشخصية من Memory", 250),
            ("الحالة", 80),
            ("", 45),
        ]

        for column, (text, width) in enumerate(headers):
            label = ctk.CTkLabel(
                header,
                text=text,
                width=width,
                font=("Segoe UI", 13, "bold")
            )
            label.grid(row=0, column=column, padx=4)

        self.accounts_frame = ctk.CTkScrollableFrame(
            self.app,
            height=390
        )
        self.accounts_frame.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=(0, 10)
        )

        self.status_label = ctk.CTkLabel(
            self.app,
            text="جاهز",
            font=("Segoe UI", 14, "bold"),
            anchor="w"
        )
        self.status_label.pack(fill="x", padx=25, pady=(0, 14))

    def create_account_row(self, account=None):
        account = account or {}
        row_index = len(self.account_rows)

        row_frame = ctk.CTkFrame(self.accounts_frame)
        row_frame.pack(fill="x", padx=4, pady=4)

        number_label = ctk.CTkLabel(
            row_frame,
            text=str(row_index + 1),
            width=35
        )
        number_label.grid(row=0, column=0, padx=4, pady=7)

        username_entry = ctk.CTkEntry(
            row_frame,
            width=210,
            placeholder_text="Username"
        )
        username_entry.grid(row=0, column=1, padx=4, pady=7)
        username_entry.insert(0, account.get("username", ""))

        password_entry = ctk.CTkEntry(
            row_frame,
            width=210,
            placeholder_text="Password",
            show="*"
        )
        password_entry.grid(row=0, column=2, padx=4, pady=7)
        password_entry.insert(0, account.get("password", ""))

        name_entry = ctk.CTkEntry(
            row_frame,
            width=250
        )
        name_entry.grid(row=0, column=3, padx=4, pady=7)
        name_entry.insert(0, account.get("character_name", ""))
        name_entry.configure(state="disabled")

        lamp = ctk.CTkLabel(
            row_frame,
            text="●",
            width=80,
            font=("Segoe UI", 28, "bold"),
            text_color="#777777"
        )
        lamp.grid(row=0, column=4, padx=4, pady=7)

        delete_button = ctk.CTkButton(
            row_frame,
            text="×",
            width=42,
            height=32,
            command=lambda idx=row_index: self.delete_account_row(idx)
        )
        delete_button.grid(row=0, column=5, padx=4, pady=7)

        self.account_rows.append({
            "frame": row_frame,
            "number": number_label,
            "username": username_entry,
            "password": password_entry,
            "name": name_entry,
            "lamp": lamp,
            "delete": delete_button,
        })

    def add_empty_account(self):
        self.create_account_row()

    def delete_account_row(self, index):
        if self.is_running:
            self.set_status("أوقف التنفيذ مؤقتًا قبل حذف حساب")
            return

        accounts = self.collect_accounts_from_ui(include_empty=True)

        if 0 <= index < len(accounts):
            accounts.pop(index)

        # Row indexes change after deletion, so stop associating old PIDs with
        # the rebuilt list until a new run registers them again.
        self.active_sessions.clear()

        self.rebuild_account_rows(accounts)
        self.save_accounts_from_ui()

    def rebuild_account_rows(self, accounts):
        for row in self.account_rows:
            row["frame"].destroy()

        self.account_rows = []

        for account in accounts:
            self.create_account_row(account)

    def load_accounts_into_ui(self):
        accounts = self.account_manager.load_accounts()

        if not accounts:
            accounts = [{
                "username": "",
                "password": "",
                "character_name": ""
            }]

        self.accounts_data = accounts
        self.rebuild_account_rows(accounts)

    def collect_accounts_from_ui(self, include_empty=False):
        accounts = []

        for row in self.account_rows:
            username = row["username"].get().strip()
            password = row["password"].get()

            row["name"].configure(state="normal")
            character_name = row["name"].get().strip()
            row["name"].configure(state="disabled")

            if include_empty or (username and password):
                accounts.append({
                    "username": username,
                    "password": password,
                    "character_name": character_name
                })

        return accounts

    def save_accounts_from_ui(self):
        accounts = self.collect_accounts_from_ui()

        if not accounts:
            self.set_status("أضف Username و Password لحساب واحد على الأقل")
            return False

        if self.account_manager.save_accounts(accounts):
            self.accounts_data = accounts
            self.set_status(f"تم حفظ {len(accounts)} حساب")
            return True

        self.set_status("حدث خطأ أثناء حفظ الحسابات")
        return False

    def set_row_state(self, index, state, page_name=None):
        def apply_update():
            if not (0 <= index < len(self.account_rows)):
                return

            row = self.account_rows[index]

            colors = {
                "idle": "#777777",
                "working": "#E0A800",
                "success": "#22C55E",
                "error": "#EF4444",
            }

            row["lamp"].configure(
                text_color=colors.get(state, "#777777")
            )

            if page_name is not None:
                row["name"].configure(state="normal")
                row["name"].delete(0, "end")
                row["name"].insert(0, page_name)
                row["name"].configure(state="disabled")

        self.app.after(0, apply_update)

    def reset_all_row_states(self):
        for index in range(len(self.account_rows)):
            self.set_row_state(index, "idle")

    # ------------------------------------------------------------------
    # File selection / settings
    # ------------------------------------------------------------------

    def select_file(self):
        path = filedialog.askopenfilename(
            title="اختار الصفحة أو البرنامج",
            filetypes=[
                ("All Files", "*.*"),
                ("Programs", "*.exe"),
                ("HTML Pages", "*.html *.htm"),
                ("Shortcuts", "*.lnk")
            ]
        )

        if not path:
            return

        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, path)
        self.save_settings()
        self.set_status("تم اختيار الملف")

    # ------------------------------------------------------------------
    # Start / Pause / Resume
    # ------------------------------------------------------------------

    def start_from_beginning(self):
        if self.is_running:
            self.set_status("البرنامج يعمل بالفعل")
            return

        if not self.save_accounts_from_ui():
            return

        self.current_account_index = 0
        self.pause_requested = False

        # A fresh run creates fresh conquer.exe processes, so remove the old
        # PID-to-row associations. This does not close any existing pages.
        self.active_sessions.clear()

        self.reset_all_row_states()
        self.is_running = True
        self.run_in_thread(self.process_accounts)

    def resume_processing(self):
        if self.is_running:
            self.set_status("البرنامج يعمل بالفعل")
            return

        if not self.save_accounts_from_ui():
            return

        if self.current_account_index >= len(self.accounts_data):
            self.set_status("تم الانتهاء من كل الحسابات - استخدم ابدأ من الأول لإعادة التشغيل")
            return

        self.pause_requested = False
        self.is_running = True
        self.run_in_thread(self.process_accounts)

    def pause_processing(self):
        if not self.is_running:
            self.set_status(
                f"متوقف مؤقتًا - الحساب التالي رقم {self.current_account_index + 1}"
            )
            return

        self.pause_requested = True
        self.set_status(
            "تم طلب الإيقاف المؤقت - سيقف قبل فتح الحساب التالي"
        )

    def process_accounts(self):
        path = self.path_entry.get().strip()
        accounts = list(self.accounts_data)
        total_accounts = len(accounts)

        if not path or not os.path.exists(path):
            self.set_status("المسار غير موجود أو لم يتم اختيار play.exe")
            self.is_running = False
            return

        while self.current_account_index < total_accounts:
            if self.pause_requested:
                self.is_running = False
                self.set_status(
                    f"متوقف مؤقتًا - الحساب التالي رقم {self.current_account_index + 1}"
                )
                return

            index = self.current_account_index
            account = accounts[index]

            self.set_row_state(index, "working")

            result, page_name = self.run_account(
                path=path,
                username=account["username"],
                password=account["password"],
                account_number=index + 1,
                total_accounts=total_accounts
            )

            if result != "SUCCESS":
                self.set_row_state(index, "error", page_name or "")
                self.is_running = False
                self.set_status(
                    f"الحساب {index + 1}: فشل - {result}"
                )
                return

            self.set_row_state(index, "success", page_name)

            # Save the name read from conquer.exe+8E6184 beside this account.
            accounts[index]["character_name"] = page_name
            self.accounts_data = accounts
            self.account_manager.save_accounts(accounts)

            # Important: advance the pointer BEFORE a possible pause.
            # Resume therefore continues with the next account, not this one.
            self.current_account_index = index + 1

            if self.pause_requested:
                self.is_running = False
                self.set_status(
                    f"متوقف مؤقتًا - الحساب التالي رقم {self.current_account_index + 1}"
                )
                return

            self.set_status(
                f"الحساب {index + 1}/{total_accounts}: تم - {page_name}"
            )
            time.sleep(1.0)

        self.is_running = False
        self.set_status(f"تم الانتهاء من {total_accounts} حساب")

    # ------------------------------------------------------------------
    # One account workflow
    # ------------------------------------------------------------------

    def run_account(self, path, username, password, account_number, total_accounts):
        previous_conquer_pids = ConquerMemoryReader.list_conquer_pids()

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري فتح صفحة جديدة..."
        )

        success, message = self.launcher.open(path)

        if not success:
            return "OPEN_ERROR", None

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري البحث عن Start Game..."
        )

        found = self.start_game_task.start()

        if not found:
            return "START_GAME_ERROR", None

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري تحديد conquer.exe الجديد..."
        )

        conquer_pid = ConquerMemoryReader.wait_for_new_conquer_pid(
            previous_conquer_pids,
            timeout=20.0
        )

        if conquer_pid is None:
            return "CONQUER_PID_ERROR", None

        try:
            memory_reader = ConquerMemoryReader(conquer_pid)
        except Exception as error:
            print(f"Could not open Conquer PID {conquer_pid}: {error}")
            return "MEMORY_OPEN_ERROR", None

        initial_name = memory_reader.read_name() or ""
        initial_state = memory_reader.read_state()

        print(
            f"Conquer PID {conquer_pid} initial name: {initial_name!r}"
        )
        print(
            f"Conquer PID {conquer_pid} initial state: "
            f"{initial_state} ({ConquerMemoryReader.state_name(initial_state)})"
        )

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري إدخال بيانات الدخول..."
        )

        login_done = self.login_task.start(
            username=username,
            password=password
        )

        if not login_done:
            memory_reader.close()
            return "LOGIN_FIELDS_ERROR", None

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري الضغط على Log In..."
        )

        if not self.login_button_task.start():
            memory_reader.close()
            return "LOGIN_BUTTON_ERROR", None

        message_type = self.post_login_task.wait_for_message(
            timeout=6.0
        )

        if message_type == PostLoginMessageTask.DISCONNECTED:
            self.set_status(
                f"الحساب {account_number}/{total_accounts}: Disconnected - إعادة Log In..."
            )

            self.post_login_task.press_ok()
            time.sleep(0.7)

            if not self.login_button_task.start():
                memory_reader.close()
                return "LOGIN_BUTTON_ERROR", None

            message_type = self.post_login_task.wait_for_message(
                timeout=6.0
            )

        if message_type == PostLoginMessageTask.WRONG_PASSWORD:
            self.set_status(
                f"الحساب {account_number}/{total_accounts}: مراجعة الباسورد..."
            )

            self.post_login_task.press_ok()
            time.sleep(0.5)

            if not self.login_task.rewrite_password(password):
                memory_reader.close()
                return "PASSWORD_RETRY_ERROR", None

            if not self.login_button_task.start():
                memory_reader.close()
                return "LOGIN_BUTTON_ERROR", None

            second_message = self.post_login_task.wait_for_message(
                timeout=6.0
            )

            if second_message == PostLoginMessageTask.WRONG_PASSWORD:
                self.post_login_task.press_ok()
                memory_reader.close()
                return "PAGE_ERROR", None

            if second_message == PostLoginMessageTask.DISCONNECTED:
                self.post_login_task.press_ok()
                time.sleep(0.7)

                if not self.login_button_task.start():
                    memory_reader.close()
                    return "LOGIN_BUTTON_ERROR", None

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري قراءة اسم الشخصية من Memory..."
        )

        page_name = memory_reader.wait_for_name_change(
            previous_value=initial_name,
            timeout=20.0,
            require_change=True
        )

        # Read the new state once as useful test output. Continuous monitoring
        # begins after the account has been registered below.
        final_state = memory_reader.read_state()
        print(
            f"Conquer PID {conquer_pid} state after login: "
            f"{final_state} ({ConquerMemoryReader.state_name(final_state)})"
        )

        memory_reader.close()

        if not page_name:
            return "MEMORY_NAME_TIMEOUT", None

        print(
            f"Account {account_number} ready - PID {conquer_pid} - Name: {page_name}"
        )

        # Register the exact PID against this account row. From this point the
        # background monitor will check STATE_OFFSET every 10 seconds.
        self.active_sessions[account_number - 1] = {
            "pid": conquer_pid,
            "username": username,
            "page_name": page_name,
        }

        return "SUCCESS", page_name

    # ------------------------------------------------------------------
    # Continuous account-state monitor (test phase: observe only)
    # ------------------------------------------------------------------

    def monitor_active_sessions(self):
        """Check every successful account's state once every 10 seconds.

        Current test behavior:
        - 7667828 / LOGGED_IN -> green lamp
        - 0 / OPEN -> red lamp
        - 7667712 / LOGGED_OUT -> red lamp
        - unknown value, dead PID, or read error -> red lamp

        No automatic relog/reopen happens in this test phase.
        """
        while not self.monitor_stop_event.is_set():
            sessions = list(self.active_sessions.items())

            for row_index, session in sessions:
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
                else:
                    self.set_row_state(row_index, "error")

            # Event.wait lets closing the program interrupt the 10-second wait.
            self.monitor_stop_event.wait(10.0)

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def save_settings(self):
        try:
            data = {
                "selected_path": self.path_entry.get().strip()
            }

            with open(
                CONFIG_FILE,
                "w",
                encoding="utf-8"
            ) as file:
                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=4
                )

        except Exception:
            pass

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE):
            return

        try:
            with open(
                CONFIG_FILE,
                "r",
                encoding="utf-8"
            ) as file:
                data = json.load(file)

            path = data.get("selected_path", "")

            if path:
                self.path_entry.insert(0, path)

        except Exception:
            pass

    def set_status(self, text):
        self.app.after(
            0,
            lambda: self.status_label.configure(text=text)
        )

    def run_in_thread(self, function):
        threading.Thread(
            target=function,
            daemon=True
        ).start()

    def close_program(self):
        self.monitor_stop_event.set()

        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        self.app.destroy()

    def run(self):
        self.app.mainloop()
