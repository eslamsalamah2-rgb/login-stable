import os
import time
import cv2
import numpy as np
import pydirectinput
import win32gui
import win32process

from PIL import ImageGrab
from tasks.base_task import BaseTask
from tasks.window_disconnect_detector import WindowDisconnectDetector
from tasks.target_window_context import TargetWindowContext


class LoginButtonTask(BaseTask):

    def __init__(self):
        super().__init__()

        self.template_path = os.path.join(
            "assets",
            "login_button.png"
        )
        self.threshold = 0.82
        self.target_pid = None
        self.window_helper = WindowDisconnectDetector()

    def set_target_pid(self, pid):
        self.target_pid = pid
        TargetWindowContext.set_pid(pid)

    def _foreground_pid(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid
        except Exception:
            return None

    def _ensure_target_window(self):
        if not self.target_pid:
            return True

        for _ in range(4):
            self.window_helper.activate_main_window(self.target_pid)
            time.sleep(0.12)
            if self._foreground_pid() == self.target_pid:
                return True
            time.sleep(0.12)

        print(
            f"Login button safety: target PID {self.target_pid} is not foreground"
        )
        return False

    def find_button(self):

        if not os.path.exists(self.template_path):
            print("Login button image not found")
            return None

        template = cv2.imread(self.template_path, cv2.IMREAD_COLOR)

        if template is None:
            return None

        template_h, template_w = template.shape[:2]

        screenshot = ImageGrab.grab()
        screen = np.array(screenshot)
        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

        result = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        _, max_value, _, max_location = cv2.minMaxLoc(result)
        print(f"Login button Match: {max_value:.3f}")

        if max_value < self.threshold:
            return None

        x = max_location[0] + template_w // 2
        y = max_location[1] + template_h // 2

        return x, y

    def start(self, target_pid=None):

        self.running = True

        if target_pid is not None:
            self.set_target_pid(target_pid)
        else:
            shared_pid = TargetWindowContext.get_pid()
            if shared_pid:
                self.target_pid = shared_pid

        start_time = time.time()

        while self.running:

            if time.time() - start_time > 30:
                print("Login button not found")
                self.running = False
                return False

            if not self._ensure_target_window():
                time.sleep(0.25)
                continue

            position = self.find_button()

            if position:
                if not self._ensure_target_window():
                    time.sleep(0.20)
                    continue

                x, y = position

                pydirectinput.moveTo(x, y, duration=0.10)
                time.sleep(0.10)

                if self.target_pid and self._foreground_pid() != self.target_pid:
                    print("Login button safety: focus changed before click; retrying")
                    continue

                pydirectinput.click()

                print(
                    f"Login button clicked on target PID {self.target_pid}"
                )

                self.running = False
                return True

            time.sleep(0.4)

        return False

    def stop(self):
        self.running = False
