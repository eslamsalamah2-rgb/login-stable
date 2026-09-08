# login-stable

Stable test baseline for the Conquer login manager.

Current health logic:
- Timer/FPS heartbeat is captured only from the exact target PID window, never from the full desktop.
- Memory state values are learned dynamically; no numeric state is hard-coded as special.
- If the same memory state is seen with the expected character name while the login page is visible in that same PID window, that state becomes timer-gated.
- Any timer-gated state must pass the in-window timer heartbeat before it can be treated as healthy.
- If timer data is missing/static/unknown while memory still equals the learned healthy state, that state is also learned as timer-gated.
- Local credentials/account files remain excluded by .gitignore.

Latest additions:
- Scan Open links already-open Conquer pages to saved account rows by the character name read from memory.
- Open pages whose memory name is not saved in the account list are shown in the side panel and are not controlled automatically.
- Settings window lets you adjust image thresholds, timer anchor threshold, Start Game/PID timeouts, and launcher retry attempts.
