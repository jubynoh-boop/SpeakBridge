type KeyStroke = { key: string; code: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean };

// RegisterHotKey expects physical keys, not the character produced by Shift.
export function shortcutFromEvent(event: KeyStroke): string | null {
  const raw = event.key.toLowerCase();
  if (["control", "shift", "alt", "meta", "dead", "unidentified"].includes(raw)) return null;
  const codes: Record<string, string> = {
    Space: "space", Escape: "esc", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    Minus: "minus", Equal: "equal", BracketLeft: "bracketleft", BracketRight: "bracketright",
    Backslash: "backslash", Semicolon: "semicolon", Quote: "quote", Backquote: "backquote", Comma: "comma", Period: "period", Slash: "slash",
  };
  const key = /^(Key[A-Z]|Digit[0-9])$/.test(event.code) ? event.code.replace(/^(Key|Digit)/, "").toLowerCase()
    : codes[event.code] || ({ " ": "space", escape: "esc", arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right" } as Record<string, string>)[raw] || raw;
  return [...(event.ctrlKey ? ["ctrl"] : []), ...(event.altKey ? ["alt"] : []), ...(event.shiftKey ? ["shift"] : []), ...(event.metaKey ? ["windows"] : []), key].join("+");
}
