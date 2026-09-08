import os
import subprocess


class Launcher:

    def __init__(self):
        self.process = None

    def open(self, path):

        if not path:
            return False, "لم يتم اختيار ملف"

        if not os.path.exists(path):
            return False, "المسار غير موجود"

        try:

            if path.lower().endswith(".exe"):

                self.process = subprocess.Popen(
                    [path]
                )

            else:

                os.startfile(path)
                self.process = None

            return True, "تم الفتح بنجاح"

        except Exception as error:

            return False, f"خطأ: {error}"

    def stop(self):

        try:

            if self.process is None:
                return False, "لا توجد عملية مسجلة"

            if self.process.poll() is not None:
                return False, "البرنامج متوقف بالفعل"

            self.process.terminate()

            return True, "تم الإيقاف"

        except Exception as error:

            return False, f"خطأ أثناء الإيقاف: {error}"