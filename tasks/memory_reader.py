import time
import psutil
import pymem
import pymem.process

from tasks.target_window_context import TargetWindowContext


class ConquerMemoryReader:

    PROCESS_NAME = "conquer.exe"

    NAME_OFFSET = 0x8E6184
    STATE_OFFSET = 0x8E52AE

    STATE_OPEN = 0
    STATE_LOGGED_IN = 7667828
    STATE_LOGGED_OUT = 7667712

    @classmethod
    def list_conquer_pids(cls):
        pids = set()

        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = process.info.get("name") or ""

                if name.lower() == cls.PROCESS_NAME:
                    pids.add(process.info["pid"])

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return pids

    @classmethod
    def terminate_all_conquer(cls, wait_timeout=5.0):
        processes = []

        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = process.info.get("name") or ""

                if name.lower() == cls.PROCESS_NAME:
                    processes.append(process)
                    process.terminate()

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        TargetWindowContext.clear()

        if not processes:
            return 0

        _, alive = psutil.wait_procs(
            processes,
            timeout=wait_timeout
        )

        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return len(processes)

    @classmethod
    def terminate_conquer_pid(cls, pid, wait_timeout=3.0):
        """Close only one Conquer page by PID."""
        try:
            process = psutil.Process(int(pid))
            process.terminate()
            try:
                process.wait(timeout=wait_timeout)
            except psutil.TimeoutExpired:
                process.kill()
            if TargetWindowContext.get_pid() == int(pid):
                TargetWindowContext.clear()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    @classmethod
    def wait_for_new_conquer_pid(cls, previous_pids, timeout=20.0):
        start_time = time.time()

        while time.time() - start_time < timeout:
            current_pids = cls.list_conquer_pids()
            new_pids = current_pids - set(previous_pids)

            if new_pids:
                # The exact newly created page becomes the only page that the
                # screen-based login tasks are allowed to touch.
                pid = max(new_pids)
                TargetWindowContext.set_pid(pid)
                print(f"Target Conquer PID locked: {pid}")
                return pid

            time.sleep(0.25)

        return None

    def __init__(self, pid):
        self.pid = int(pid)
        self.pm = pymem.Pymem()
        self.pm.open_process_from_id(self.pid)

    def close(self):
        try:
            self.pm.close_process()
        except Exception:
            pass

    def _module_base(self):
        module = pymem.process.module_from_name(
            self.pm.process_handle,
            self.PROCESS_NAME
        )

        if module is None:
            return None

        return module.lpBaseOfDll

    def read_name(self, max_length=64):
        try:
            module_base = self._module_base()

            if module_base is None:
                return None

            address = module_base + self.NAME_OFFSET
            value = self.pm.read_string(address, max_length)

            if value is None:
                return None

            return value.strip("\x00").strip()

        except Exception as error:
            print(
                f"Memory name read error for PID {self.pid}: {error}"
            )
            return None

    def read_state(self):
        try:
            module_base = self._module_base()

            if module_base is None:
                return None

            address = module_base + self.STATE_OFFSET
            return self.pm.read_int(address)

        except Exception as error:
            print(
                f"Memory state read error for PID {self.pid}: {error}"
            )
            return None

    @classmethod
    def state_name(cls, value):
        if value == cls.STATE_OPEN:
            return "OPEN"

        if value == cls.STATE_LOGGED_IN:
            return "LOGGED_IN"

        if value == cls.STATE_LOGGED_OUT:
            return "LOGGED_OUT"

        if value is None:
            return "READ_ERROR"

        return f"UNKNOWN({value})"

    def wait_for_name_change(
        self,
        previous_value=None,
        timeout=None,
        require_change=True,
        check_interval=10.0
    ):
        previous_value = (previous_value or "").strip()
        check_number = 0

        while True:
            check_number += 1
            value = self.read_name()

            print(
                f"Memory name check #{check_number} - PID {self.pid} - "
                f"Value: {value!r}"
            )

            if value:
                if not require_change:
                    return value

                if value != previous_value:
                    return value

            print(
                f"Name not ready yet. Checking again in "
                f"{check_interval:g} seconds..."
            )
            time.sleep(check_interval)
