import customtkinter as ctk

from health_launcher import HealthAwareLauncher
from tasks.memory_reader import ConquerMemoryReader


class ClearAllAwareLauncher(HealthAwareLauncher):
    """Adds a Clear All control that closes every existing Conquer page."""

    def __init__(self):
        super().__init__()

        controls = self.resume_button.master

        self.clear_all_button = ctk.CTkButton(
            controls,
            text="Clear All",
            width=120,
            height=40,
            command=self.clear_all_pages,
        )
        self.clear_all_button.pack(side="left", padx=6, pady=10)

    def clear_all_pages(self):
        """Stop automation and close all conquer.exe pages on this PC.

        Account credentials are not deleted. The account pointer and health
        associations are reset so the next fresh start begins cleanly.
        """
        # Use the existing global pause path first so image scans, memory scans,
        # timer checks, and account-opening work all stop before processes die.
        self.pause_processing()
        self.set_status("Clear All - جاري إغلاق كل صفحات Conquer الموجودة...")
        self.run_in_thread(self._clear_all_pages_worker)

    def _clear_all_pages_worker(self):
        closed_count = ConquerMemoryReader.terminate_all_conquer()

        self.active_sessions.clear()

        try:
            with self.recovering_accounts_lock:
                self.recovering_accounts.clear()
        except Exception:
            pass

        self.current_account_index = 0
        self.is_running = False
        self.reset_all_row_states()

        print(f"Clear All: closed {closed_count} conquer.exe process(es)")
        self.set_status(
            f"Clear All تم - اتقفل {closed_count} صفحة Conquer. الحسابات المحفوظة لم تُحذف"
        )
