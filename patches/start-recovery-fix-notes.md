# Start/recovery fix notes

Changes for the current test:

- Retry Start Game up to 3 times when the click does not create a new `conquer.exe` PID.
- Pass the launcher PID into Start Game / PID detection so logs show which launcher was used.
- Keep waiting logs visible instead of appearing frozen after `Start Game clicked`.
- Accept the stable exact-PID login-fields near-match case around `0.798` only when color and grayscale agree tightly.
- During recovery, do not trust memory name/state alone; require a live in-window timer before marking the page Ready.
