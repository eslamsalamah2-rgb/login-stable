import time

from gui import SimpleLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask


class MaintenanceAwareLauncher(SimpleLauncher):
    """SimpleLauncher with maintenance and client-update recovery."""

    MAINTENANCE_RETRY_SECONDS = 60
    UPDATE_RETRY_SECONDS = 5

    def _maintenance_result(self, memory_reader):
        self.post_login_task.press_ok()

        if memory_reader is not None:
            memory_reader.close()

        return "SERVER_MAINTENANCE", None

    def _client_update_result(self, memory_reader):
        self.post_login_task.press_ok()

        if memory_reader is not None:
            memory_reader.close()

        return "CLIENT_UPDATE", None

    def _wait_maintenance_retry(self):
        remaining = self.MAINTENANCE_RETRY_SECONDS

        while remaining > 0:
            if self.pause_requested:
                return False

            self.set_status(
                f"صيانة السيرفر - المحاولة التالية بعد {remaining} ثانية"
            )

            time.sleep(1.0)
            remaining -= 1

        return True

    def _wait_update_retry(self):
        remaining = self.UPDATE_RETRY_SECONDS

        while remaining > 0:
            if self.pause_requested:
                return False

            self.set_status(
                f"يوجد Update - إعادة فتح اللعبة بعد {remaining} ثانية"
            )
            time.sleep(1.0)
            remaining -= 1

        return True



    def _restart_all_accounts_after_password_error(self, account_number, reason):
        """Close every Conquer page and restart from account 1 after a repeated password message.

        The first Wrong password message can be caused by an empty/not-written
        password field after a focus interruption.  If it appears again after
        rewriting the password, we treat the whole current game-page group as
        unsafe and restart cleanly from the first selected account.
        """
        self.set_status(
            f"الحساب {account_number}: رسالة Wrong password ظهرت مرة ثانية بعد إعادة كتابة الباسورد - "
            "إغلاق كل الصفحات والبدء من الأول..."
        )

        closed_count = ConquerMemoryReader.terminate_all_conquer()
        print(
            f"Repeated password message after rewrite - account {account_number} - "
            f"reason={reason} - closed {closed_count} conquer.exe process(es); restarting all accounts"
        )

        self.active_sessions.clear()
        self.current_account_index = 0

        try:
            with self.recovering_accounts_lock:
                self.recovering_accounts.clear()
        except Exception:
            pass

        self.reset_all_row_states()
        time.sleep(1.0)
        return "RESTART_ALL_ACCOUNTS", None

    def _current_launcher_pid(self):
        try:
            if self.launcher.process is None:
                return None
            if self.launcher.process.poll() is not None:
                return None
            return self.launcher.process.pid
        except Exception:
            return None

    def _stop_launcher_only(self):
        try:
            process = self.launcher.process
            if process is not None and process.poll() is None:
                process.terminate()
        except Exception:
            pass

    def _open_conquer_pid_with_retries(self, path, account_number, total_accounts):
        """Open launcher, click Start Game, and confirm a new conquer.exe PID.

        Sometimes the launcher button is visibly clicked but no Conquer page is
        created.  In that case we reopen the launcher and retry instead of
        leaving the account stuck after "Start Game clicked".
        """
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            previous_conquer_pids = ConquerMemoryReader.list_conquer_pids()

            self.set_status(
                f"الحساب {account_number}/{total_accounts}: فتح اللانشر "
                f"محاولة {attempt}/{max_attempts}..."
            )

            success, message = self.launcher.open(path)
            if not success:
                return None, "OPEN_ERROR"

            time.sleep(0.8)

            launcher_pid = self._current_launcher_pid()

            self.set_status(
                f"الحساب {account_number}/{total_accounts}: البحث عن Start Game "
                f"محاولة {attempt}/{max_attempts}..."
            )

            found = self.start_game_task.start(
                target_pid=launcher_pid,
                timeout=20.0,
            )

            if not found:
                print(
                    f"Start Game attempt {attempt}/{max_attempts} failed - "
                    "button not found"
                )
                self._stop_launcher_only()
                time.sleep(1.0)
                continue

            self.set_status(
                f"الحساب {account_number}/{total_accounts}: انتظار صفحة Conquer "
                f"الجديدة محاولة {attempt}/{max_attempts}..."
            )

            conquer_pid = ConquerMemoryReader.wait_for_new_conquer_pid(
                previous_conquer_pids,
                timeout=20.0,
                launcher_pid=launcher_pid,
            )

            if conquer_pid is not None:
                return conquer_pid, "SUCCESS"

            print(
                f"Start Game attempt {attempt}/{max_attempts} clicked but no "
                "new Conquer PID appeared - retrying with a fresh launcher"
            )
            self._stop_launcher_only()
            time.sleep(1.0)

        return None, "CONQUER_PID_ERROR"

    def process_accounts(self):
        path = self.path_entry.get().strip()
        accounts = list(self.accounts_data)
        total_accounts = len(accounts)

        if not path:
            self.set_status("لم يتم اختيار play.exe")
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

            if result == "SERVER_MAINTENANCE":
                self.set_status(
                    "تم اكتشاف صيانة السيرفر - جاري إغلاق كل صفحات Conquer..."
                )

                closed_count = ConquerMemoryReader.terminate_all_conquer()
                print(
                    f"Server maintenance: closed {closed_count} conquer.exe process(es)"
                )

                self.active_sessions.clear()
                self.current_account_index = 0
                self.reset_all_row_states()

                if not self._wait_maintenance_retry():
                    self.is_running = False
                    self.set_status("متوقف مؤقتًا أثناء انتظار صيانة السيرفر")
                    return

                continue

            if result == "CLIENT_UPDATE":
                self.set_status(
                    "تم اكتشاف Update - جاري إغلاق كل صفحات Conquer وإعادة فتح اللعبة..."
                )

                closed_count = ConquerMemoryReader.terminate_all_conquer()
                print(
                    f"Client update: closed {closed_count} conquer.exe process(es)"
                )

                self.active_sessions.clear()
                self.current_account_index = 0
                self.reset_all_row_states()

                if not self._wait_update_retry():
                    self.is_running = False
                    self.set_status("متوقف مؤقتًا أثناء انتظار الـ Update")
                    return

                continue

            if result == "RESTART_ALL_ACCOUNTS":
                self.set_status(
                    "تم إغلاق كل صفحات Conquer بسبب تكرار Wrong password بعد إعادة كتابة الباسورد - "
                    "جاري البدء من الحساب الأول..."
                )
                continue

            if result == "PAGE_TIMEOUT_RETRY":
                self.set_row_state(index, "working")
                self.set_status(
                    f"الحساب {index + 1}: إعادة المحاولة بصفحة جديدة..."
                )
                continue

            if result != "SUCCESS":
                self.set_row_state(index, "error", page_name or "")
                self.is_running = False
                self.set_status(
                    f"الحساب {index + 1}: فشل - {result}"
                )
                return

            self.set_row_state(index, "success", page_name)

            accounts[index]["character_name"] = page_name
            self.accounts_data = accounts
            self.account_manager.save_accounts(accounts)

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

    def run_account(self, path, username, password, account_number, total_accounts):
        conquer_pid, launch_result = self._open_conquer_pid_with_retries(
            path=path,
            account_number=account_number,
            total_accounts=total_accounts,
        )

        if conquer_pid is None:
            return launch_result, None

        page_started_at = time.time()

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
            password=password,
            target_pid=conquer_pid,
        )

        if not login_done:
            memory_reader.close()
            print(
                f"Login fields/input failed for PID {conquer_pid} - closing this page "
                "and retrying the same account from the launcher"
            )
            ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
            time.sleep(1.0)
            return "PAGE_TIMEOUT_RETRY", None

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري الضغط على Log In..."
        )

        if not self.login_button_task.start(target_pid=conquer_pid):
            memory_reader.close()
            return "LOGIN_BUTTON_ERROR", None

        message_type = self.post_login_task.wait_for_message(
            timeout=6.0
        )

        if message_type == PostLoginMessageTask.SERVER_MAINTENANCE:
            return self._maintenance_result(memory_reader)

        if message_type == PostLoginMessageTask.CLIENT_UPDATE:
            return self._client_update_result(memory_reader)

        if message_type == PostLoginMessageTask.DISCONNECTED:
            self.set_status(
                f"الحساب {account_number}/{total_accounts}: Disconnected - إعادة Log In..."
            )

            self.post_login_task.press_ok()
            time.sleep(0.7)

            if not self.login_button_task.start(target_pid=conquer_pid):
                memory_reader.close()
                return "LOGIN_BUTTON_ERROR", None

            message_type = self.post_login_task.wait_for_message(
                timeout=6.0
            )

            if message_type == PostLoginMessageTask.SERVER_MAINTENANCE:
                return self._maintenance_result(memory_reader)

            if message_type == PostLoginMessageTask.CLIENT_UPDATE:
                return self._client_update_result(memory_reader)

        if message_type == PostLoginMessageTask.WRONG_PASSWORD:
            self.set_status(
                f"الحساب {account_number}/{total_accounts}: Wrong password - غالبًا الباسورد لم يُكتب؛ إعادة كتابته من الأول..."
            )
            print(
                f"Wrong password message detected after first Log In - account {account_number} - "
                f"PID {conquer_pid}; pressing OK and rewriting password"
            )

            self.post_login_task.press_ok()
            time.sleep(0.5)

            if not self.login_task.rewrite_password(
                password,
                target_pid=conquer_pid,
            ):
                memory_reader.close()
                return "PASSWORD_RETRY_ERROR", None

            if not self.login_button_task.start(target_pid=conquer_pid):
                memory_reader.close()
                return "LOGIN_BUTTON_ERROR", None

            second_message = self.post_login_task.wait_for_message(
                timeout=6.0
            )

            if second_message == PostLoginMessageTask.SERVER_MAINTENANCE:
                return self._maintenance_result(memory_reader)

            if second_message == PostLoginMessageTask.CLIENT_UPDATE:
                return self._client_update_result(memory_reader)

            if second_message == PostLoginMessageTask.WRONG_PASSWORD:
                print(
                    f"Wrong password message repeated after password rewrite - account {account_number} - "
                    f"PID {conquer_pid}; restarting all pages from the beginning"
                )
                self.post_login_task.press_ok()
                memory_reader.close()
                return self._restart_all_accounts_after_password_error(
                    account_number,
                    "NORMAL_LOGIN_WRONG_PASSWORD_AFTER_REWRITE",
                )

            if second_message == PostLoginMessageTask.DISCONNECTED:
                self.post_login_task.press_ok()
                time.sleep(0.7)

                if not self.login_button_task.start(target_pid=conquer_pid):
                    memory_reader.close()
                    return "LOGIN_BUTTON_ERROR", None

                third_message = self.post_login_task.wait_for_message(
                    timeout=6.0
                )

                if third_message == PostLoginMessageTask.SERVER_MAINTENANCE:
                    return self._maintenance_result(memory_reader)

                if third_message == PostLoginMessageTask.CLIENT_UPDATE:
                    return self._client_update_result(memory_reader)

                if third_message == PostLoginMessageTask.WRONG_PASSWORD:
                    print(
                        f"Wrong password message repeated after disconnected retry - account {account_number} - "
                        f"PID {conquer_pid}; restarting all pages from the beginning"
                    )
                    self.post_login_task.press_ok()
                    memory_reader.close()
                    return self._restart_all_accounts_after_password_error(
                        account_number,
                        "NORMAL_LOGIN_DISCONNECTED_WRONG_PASSWORD_AFTER_REWRITE",
                    )

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: جاري قراءة اسم الشخصية من Memory..."
        )

        page_name = None
        name_check_number = 0

        while time.time() - page_started_at < 90.0:
            name_check_number += 1
            current_name = memory_reader.read_name() or ""
            print(
                f"Memory name check #{name_check_number} - PID {conquer_pid} - "
                f"Value: {current_name!r}"
            )

            if current_name and current_name != initial_name:
                page_name = current_name
                break

            if self.post_login_task.is_server_crowded():
                self.set_status(
                    f"الحساب {account_number}/{total_accounts}: السيرفر مزدحم - "
                    "إعادة Log In بعد 10 ثواني..."
                )
                time.sleep(10.0)

                if not self.login_button_task.start(target_pid=conquer_pid):
                    memory_reader.close()
                    return "LOGIN_BUTTON_ERROR", None

                continue

            remaining = max(0, int(90 - (time.time() - page_started_at)))
            print(
                f"Name not ready yet. Page timeout in {remaining} seconds..."
            )
            time.sleep(2.0)

        if not page_name:
            memory_reader.close()
            self.set_status(
                f"الحساب {account_number}/{total_accounts}: الصفحة لم تصبح Ready خلال دقيقة ونصف - "
                "إغلاقها وفتح صفحة جديدة..."
            )
            ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
            time.sleep(1.0)
            return "PAGE_TIMEOUT_RETRY", None

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

        self.active_sessions[account_number - 1] = {
            "pid": conquer_pid,
            "username": username,
            "password": password,
            "page_name": page_name,
        }

        return "SUCCESS", page_name
