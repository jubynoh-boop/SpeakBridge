from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.hotkey_helper import VoiceTypingHelper


time.sleep(0.8)
window = int(sys.argv[1])
control = int(sys.argv[2])
text = base64.b64decode(sys.argv[3]).decode("utf-8")
VoiceTypingHelper._paste_text(text, window, control)
