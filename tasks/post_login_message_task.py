import os
import time
import cv2
import numpy as np
import pydirectinput

from PIL import ImageGrab
from tasks.base_task import BaseTask


class PostLoginMessageTask(BaseTask):

    DISCONNECTED = "DISCONNECTED"
    WRONG_PASSWORD = "WRONG_PASSWORD"
    INVALID_ACCOUNT_PASSWORD = "INVALID_ACCOUNT_PASSWORD"
    SERVER_MAINTENANCE = "SERVER_MAINTENANCE"
    CLIENT_UPDATE = "CLIENT_UPDATE"
    SERVER_CROWDED = "SERVER_CROWDED"

    def __init__(self):
        super().__init__()

        self.templates = {
            self.DISCONNECTED: os.path.join(
                "assets",
                "disconnected.png"
            ),
            self.WRONG_PASSWORD: os.path.join(
                "assets",
                "wrong_password.png"
            ),
            self.INVALID_ACCOUNT_PASSWORD: os.path.join(
                "assets",
                "invalid_account_password.png"
            ),
            self.SERVER_MAINTENANCE: os.path.join(
                "assets",
                "server_maintenance.png"
            ),
            self.CLIENT_UPDATE: os.path.join(
                "assets",
                "client_update.png"
            ),
            self.SERVER_CROWDED: os.path.join(
                "assets",
                "server_crowded.png"
            )
        }

        self.ok_template_path = os.path.join(
            "assets",
            "ok_button.png"
        )

        self.threshold = 0.82
        self.ok_threshold = 0.82

    def _load_screen(self):
        screenshot = ImageGrab.grab()
        screen = np.array(screenshot)
        return cv2.cvtColor(
            screen,
            cv2.COLOR_RGB2BGR
        )

    def _match_template(self, screen, template_path):
        if not os.path.exists(template_path):
            return 0.0, None, None

        template = cv2.imread(
            template_path,
            cv2.IMREAD_COLOR
        )

        if template is None:
            return 0.0, None, None

        screen_h, screen_w = screen.shape[:2]
        template_h, template_w = template.shape[:2]

        if template_w > screen_w or template_h > screen_h:
            return 0.0, None, None

        result = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        _, max_value, _, max_location = cv2.minMaxLoc(result)

        center = (
            max_location[0] + template_w // 2,
            max_location[1] + template_h // 2
        )

        return max_value, center, (template_w, template_h)

    def detect(self):
        screen = self._load_screen()

        best_type = None
        best_value = 0.0

        for message_type, template_path in self.templates.items():
            value, _, _ = self._match_template(
                screen,
                template_path
            )

            print(
                f"Post login {message_type} Match: {value:.3f}"
            )

            if value > best_value:
                best_value = value
                best_type = message_type

        if best_value < self.threshold:
            return None

        if best_type == self.INVALID_ACCOUNT_PASSWORD:
            return self.WRONG_PASSWORD

        return best_type

    def is_server_crowded(self):
        """Check only the crowded-server text without changing old message flow."""
        screen = self._load_screen()
        value, _, _ = self._match_template(
            screen,
            self.templates[self.SERVER_CROWDED]
        )
        print(f"Post login SERVER_CROWDED Match: {value:.3f}")
        return value >= self.threshold

    def wait_for_message(self, timeout=6.0):
        self.running = True
        start_time = time.time()

        while self.running:
            message_type = self.detect()

            if message_type:
                self.running = False
                return message_type

            if time.time() - start_time >= timeout:
                self.running = False
                return None

            time.sleep(0.25)

        return None

    def press_ok(self, timeout=3.0):
        start_time = time.time()

        while time.time() - start_time < timeout:
            screen = self._load_screen()
            value, center, _ = self._match_template(
                screen,
                self.ok_template_path
            )

            print(f"Post login OK Match: {value:.3f}")

            if value >= self.ok_threshold and center:
                pydirectinput.moveTo(
                    center[0],
                    center[1],
                    duration=0.05
                )
                pydirectinput.click()
                time.sleep(0.5)
                return True

            time.sleep(0.15)

        pydirectinput.press("enter")
        time.sleep(0.5)
        return False

    def is_password_error(self, message_type):
        return message_type in {
            self.WRONG_PASSWORD,
            self.INVALID_ACCOUNT_PASSWORD
        }

    def stop(self):
        self.running = False
