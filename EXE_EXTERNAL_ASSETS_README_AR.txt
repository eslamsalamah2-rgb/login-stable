طريقة عمل EXE مع الصور خارج الملف

1) افتح PowerShell أو CMD داخل فولدر المشروع:
   C:\Users\Eslam\Desktop\login-stable-git

2) شغل الملف:
   BUILD_EXE_EXTERNAL_ASSETS.bat

3) بعد البناء هتلاقي:
   dist\ZERO_LOGIN_BOT.exe
   dist\assets\
   dist\accounts.json
   dist\settings.json
   dist\item_selections.json

4) الصور لازم تفضل خارج الـ EXE في فولدر assets جنب الـ EXE:
   dist\assets\login_fields.png
   dist\assets\ok_button.png
   dist\assets\invalid_account_id.png
   dist\assets\password_length_error.png
   dist\assets\inventory_open.png
   dist\assets\drop_confirm_yes.png
   dist\assets\Revive.png
   dist\assets\sash_button.png
   dist\assets\sash_next.png
   dist\assets\drop_items\*.png
   dist\assets\use_items\*.png
   dist\assets\sash_items\*.png

5) لو عدلت أي صورة بعد كده، اقفل البرنامج وافتحه تاني.

6) ما ترفعش accounts.json أو settings.json أو item_selections.json على GitHub لو فيهم بياناتك الخاصة.
