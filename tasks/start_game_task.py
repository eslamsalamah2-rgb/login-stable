import os
import time
import cv2
import numpy as np
import pydirectinput

from PIL import ImageGrab
from tasks.base_task import BaseTask


class StartGameTask(BaseTask):

    def __init__(self):
        super().__init__()

        self.template_path = os.path.join(
            "assets",
            "start_game.png"
        )

        self.threshold = 0.82

    def find_start_button(self):

        if not os.path.exists(self.template_path):
            print("Start Game image not found")
            return None

        template = cv2.imread(
            self.template_path,
            cv2.IMREAD_COLOR
        )

        if template is None:
            return None

        template_height, template_width = template.shape[:2]

        screenshot = ImageGrab.grab()

        screen = np.array(screenshot)

        screen = cv2.cvtColor(
            screen,
            cv2.COLOR_RGB2BGR
        )

        result = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        _, max_value, _, max_location = cv2.minMaxLoc(
            result
        )

        print(
            f"Start Game Match: {max_value:.3f}"
        )

        if max_value < self.threshold:
            return None

        x = max_location[0] + template_width // 2
        y = max_location[1] + template_height // 2

        return x, y

    def start(self):

        self.running = True

        print("Searching for Start Game...")

        # يدور لمدة 30 ثانية
        start_time = time.time()

        while self.running:

            if time.time() - start_time > 30:

                print(
                    "Start Game button not found"
                )

                self.running = False
                return False

            position = self.find_start_button()

            if position:

                x, y = position

                print(
                    f"Start Game found: {x}, {y}"
                )

                pydirectinput.moveTo(
                    x,
                    y,
                    duration=0.15
                )

                time.sleep(0.2)

                pydirectinput.click()

                print(
                    "Start Game clicked"
                )

                self.running = False

                return True

            time.sleep(0.5)

        return False

    def stop(self):

        self.running = False