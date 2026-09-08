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
    def wait_for_new_conquer_pid(cls, previous_pids, timeout=30.0, launcher_pid=None):
        """Wait for the Conquer page created by the current Start Game click.

        Primary detection remains the safe rule used by the stable build: a
        conquer.exe PID that did not exist before this launch. We also inspect
        the launcher child-process tree as a second source so a newly spawned
        Conquer process is not missed during the short hand-off from play.exe.

        The function logs its wait state instead of appearing frozen.
        """
        start_time = time.time()
        previous_pids = set(previous_pids or ())
        last_progress_second = -1

        print(
            f"Waiting for new Conquer PID - before={sorted(previous_pids)} "
            f"- launcher_pid={launcher_pid}"
        )

        while time.time() - start_time < timeout:
            current_pids = cls.list_conquer_pids()
            new_pids = current_pids - previous_pids

            # Normal/primary path: a brand-new conquer.exe process. Choose the
            # newest process by creation time rather than the numerically largest
            # PID, because PID numbers are not a reliable creation-order signal.
            if new_pids:
                def _created_at(pid):
                    try:
                        return psutil.Process(pid).create_time()
                    except Exception:
                        return 0.0

                pid = max(new_pids, key=_created_at)
                TargetWindowContext.set_pid(pid)
                print(f"Target Conquer PID locked: {pid} (new process)")
                return pid

            # Secondary path: inspect descendants of the exact play.exe process
            # opened for this account. This helps during launcher hand-off while
            # still requiring the child executable itself to be conquer.exe.
            if launcher_pid:
                try:
                    launcher_process = psutil.Process(int(launcher_pid))
                    descendants = launcher_process.children(recursive=True)
                    child_candidates = []

                    for child in descendants:
                        try:
                            if child.pid in previous_pids:
                                continue
                            if (child.name() or "").lower() != cls.PROCESS_NAME:
                                continue
                            child_candidates.append(child)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if child_candidates:
                        child_candidates.sort(
                            key=lambda proc: proc.create_time(),
                            reverse=True,
                        )
                        pid = child_candidates[0].pid
                        TargetWindowContext.set_pid(pid)
                        print(f"Target Conquer PID locked: {pid} (launcher child)")
                        return pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            elapsed = int(time.time() - start_time)
            if elapsed != last_progress_second and elapsed % 2 == 0:
                last_progress_second = elapsed
                print(
                    f"Waiting for new Conquer PID... {elapsed}/{int(timeout)}s "
                    f"- current={sorted(current_pids)}"
                )

            time.sleep(0.25)

        final_pids = cls.list_conquer_pids()
        print(
            f"New Conquer PID timeout after {timeout:.0f}s - "
            f"before={sorted(previous_pids)} - current={sorted(final_pids)}"
        )
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
