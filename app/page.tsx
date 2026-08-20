"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type State = "processing" | "done" | "error";
type FeedItem = { id: string; source: string; translation: string; sourceLang: string; targetLang: string; latencyMs?: number; state: State };
type DeviceOption = { deviceId: string; label: string };
type ModelAsset = { name: string; role: string; processor: string; installed: boolean; size_gb: number; path: string };
type UiLanguage = "vi" | "en";

const HTTP = "http://127.0.0.1:8765";
const OUT_WS = "ws://127.0.0.1:8765/ws/audio";
const IN_WS = "ws://127.0.0.1:8765/ws/system-audio";

const LANGUAGES = [
  ["vi", "Tiếng Việt", "Vietnamese"], ["en", "Tiếng Anh", "English"], ["zh", "Tiếng Trung", "Chinese"],
] as const;

const COPY = {
  vi: {
    twoWay: "Hai chiều · Local AI", online: "Local engine online", offline: "Backend offline", settings: "Cài đặt",
    eyebrow: "PHIÊN DỊCH HỌP HAI CHIỀU", heroA: "Nghe bên kia bằng ngôn ngữ của bạn.", heroB: "Nói ra ngôn ngữ họ cần.",
    lead: "Mỗi luồng có ngôn ngữ vào/ra riêng. Âm thanh bên kia chỉ tạo phụ đề; giọng của bạn có thể phát qua VB-CABLE.",
    controls: "Điều khiển hai luồng", myVoice: "Tôi nói → dịch + giọng đọc", microphone: "Microphone", defaultMic: "Microphone mặc định",
    ttsOutput: "Đầu ra giọng dịch", defaultSpeaker: "Loa mặc định", routeWarn: "Loa mặc định có thể bị 02A thu lại. Khi họp hãy chọn CABLE Input.",
    routeOk: "Meet chọn mic CABLE Output; loa Meet và 02A vẫn chọn tai nghe thật.", sourceLanguage: "Ngôn ngữ nói", targetLanguage: "Ngôn ngữ dịch",
    voice: "Giọng đọc", speak: "Phát giọng dịch", textOnly: "Ngôn ngữ này hiện chỉ có phụ đề; TTS local hỗ trợ Anh và Trung.",
    startMe: "Bắt đầu tôi nói", stopMic: "Dừng microphone", preparing: "Đang chuẩn bị…", otherSide: "Bên kia → phụ đề",
    playbackDevice: "Thiết bị đang phát Meet / Discord / YouTube", defaultPlayback: "Thiết bị phát mặc định Windows",
    playbackHelp: "Chọn tai nghe/loa thật đang phát tiếng bên kia; không chọn CABLE Input/In 16ch.", startOther: "Bắt đầu nghe bên kia", stopOther: "Dừng nghe bên kia",
    mode: "Chế độ dùng chung", context: "Ngữ cảnh cuộc họp", contextHelp: "Có tác dụng thật: gửi vào cả Whisper và Hy-MT2. Viết 1–3 câu mô tả chủ đề, ví dụ thanh toán, y tế hoặc kỹ thuật.", glossary: "Hotwords / Glossary",
    glossaryHelp: "Có tác dụng thật: mỗi dòng là một tên riêng hoặc thuật ngữ Whisper cần ưu tiên và giữ đúng cách viết.", auto: "Tự nhận diện", export: "Xuất .doc", clear: "Xóa lịch sử",
    emptyOther: "Phụ đề bên kia xuất hiện tại đây", emptyMe: "Bản dịch giọng bạn xuất hiện tại đây", recognizing: "Đang nhận dạng…", translating: "Đang dịch…",
    uiLanguage: "Ngôn ngữ giao diện", translator: "Model dịch", storage: "Lịch sử chỉ nằm trong RAM và mất khi tải lại; không làm ổ đĩa phình to.", close: "Đóng",
    hotkeyTitle: "Voice Typing toàn Windows", hotkeyHelp: "Đặt con trỏ vào ô nhập, giữ phím tắt để nói rồi thả ra. Helper sẽ nhận dạng hoặc dịch và dán chữ; không tự nhấn Enter.", hotkeyLabel: "Phím tắt giữ để nói", hotkeyCapture: "Nhấp vào đây rồi bấm tổ hợp phím", hotkeyMic: "Microphone Voice Typing", hotkeyTranslate: "Dịch trước khi nhập", hotkeySave: "Lưu cấu hình hotkey", hotkeySaved: "Đã lưu · helper tự cập nhật trong vài giây",
    readyMic: "Sẵn sàng nhận microphone", readyOther: "Sẵn sàng nghe Meet / Discord", stoppedMic: "Đã dừng microphone", stoppedOther: "Đã dừng nghe bên kia",
  },
  en: {
    twoWay: "Two-way · Local AI", online: "Local engine online", offline: "Backend offline", settings: "Settings",
    eyebrow: "TWO-WAY MEETING INTERPRETER", heroA: "Hear them in your language.", heroB: "Speak in the language they need.",
    lead: "Each stream has independent input/output languages. Remote audio produces subtitles; your translated voice can be routed through VB-CABLE.",
    controls: "Two-stream controls", myVoice: "My voice → translation + speech", microphone: "Microphone", defaultMic: "Default microphone",
    ttsOutput: "Translated voice output", defaultSpeaker: "Default speaker", routeWarn: "The default speaker may be captured by 02A. Select CABLE Input during calls.",
    routeOk: "Meet microphone: CABLE Output; Meet speaker and 02A: physical headphones.", sourceLanguage: "Spoken language", targetLanguage: "Translation language",
    voice: "Voice", speak: "Play translated speech", textOnly: "This language is subtitle-only; local TTS currently supports English and Chinese.",
    startMe: "Start my microphone", stopMic: "Stop microphone", preparing: "Preparing…", otherSide: "Remote side → subtitles",
    playbackDevice: "Device playing Meet / Discord / YouTube", defaultPlayback: "Windows default playback device",
    playbackHelp: "Select the physical headphones/speakers playing the remote side; do not select CABLE Input/In 16ch.", startOther: "Start remote listening", stopOther: "Stop remote listening",
    mode: "Shared mode", context: "Meeting context", contextHelp: "Active in the backend: sent to both Whisper and Hy-MT2. Write 1–3 sentences describing the meeting topic.", glossary: "Hotwords / Glossary",
    glossaryHelp: "Active in the backend: one proper name or technical term per line for Whisper priority and exact casing.", auto: "Auto detect", export: "Export .doc", clear: "Clear history",
    emptyOther: "Remote subtitles will appear here", emptyMe: "Your translated speech will appear here", recognizing: "Recognizing…", translating: "Translating…",
    uiLanguage: "Interface language", translator: "Translation model", storage: "History stays in RAM and is cleared on reload; it does not grow disk usage.", close: "Close",
    hotkeyTitle: "Windows-wide Voice Typing", hotkeyHelp: "Focus a text field, hold the shortcut while speaking, then release. The helper transcribes or translates and pastes text without pressing Enter.", hotkeyLabel: "Push-to-talk shortcut", hotkeyCapture: "Click here, then press the key combination", hotkeyMic: "Voice Typing microphone", hotkeyTranslate: "Translate before typing", hotkeySave: "Save hotkey settings", hotkeySaved: "Saved · helper reloads within a few seconds",
    readyMic: "Microphone ready", readyOther: "Ready for Meet / Discord audio", stoppedMic: "Microphone stopped", stoppedOther: "Remote listening stopped",
  },
} as const;

function resampleTo16k(input: Float32Array, sourceRate: number) {
  if (sourceRate === 16000) return input;
  const ratio = sourceRate / 16000;
  const output = new Float32Array(Math.max(1, Math.round(input.length / ratio)));
  for (let i = 0; i < output.length; i += 1) {
    const position = i * ratio; const left = Math.floor(position); const right = Math.min(left + 1, input.length - 1); const mix = position - left;
    output[i] = input[left] * (1 - mix) + input[right] * mix;
  }
  return output;
}

function floatToPcm16(input: Float32Array) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) { const value = Math.max(-1, Math.min(1, input[i])); output[i] = value < 0 ? value * 0x8000 : value * 0x7fff; }
  return output;
}

function languageName(code: string, ui: UiLanguage) {
  if (code === "auto") return ui === "vi" ? "Tự nhận diện" : "Auto detect";
  const item = LANGUAGES.find(([value]) => value === code);
  return item ? item[ui === "vi" ? 1 : 2] : code.toUpperCase();
}

function escapeHtml(value: string) { return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!)); }

function LanguageSelect({ value, onChange, allowAuto = false, disabled = false }: { value: string; onChange: (value: string) => void; allowAuto?: boolean; disabled?: boolean }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>{allowAuto && <option value="auto">AUTO · Tự nhận diện</option>}{LANGUAGES.map(([code, vi, en]) => <option key={code} value={code}>{vi} · {en}</option>)}</select>;
}

export default function Home() {
  const [uiLang, setUiLang] = useState<UiLanguage>("vi"); const t = COPY[uiLang];
  const [settingsOpen, setSettingsOpen] = useState(false); const [modelAssets, setModelAssets] = useState<ModelAsset[]>([]); const [modelCacheRoot, setModelCacheRoot] = useState(""); const [online, setOnline] = useState(false); const [mode, setMode] = useState<"fast" | "quality">("fast");
  const [micDevices, setMicDevices] = useState<DeviceOption[]>([]); const [outputDevices, setOutputDevices] = useState<DeviceOption[]>([]); const [speakerDevices, setSpeakerDevices] = useState<string[]>([]);
  const [micId, setMicId] = useState("default"); const [outputId, setOutputId] = useState("default"); const [speakerDevice, setSpeakerDevice] = useState("__default__");
  const [outSource, setOutSource] = useState("vi"); const [outTarget, setOutTarget] = useState("en"); const [inSource, setInSourceState] = useState("auto"); const [inTarget, setInTargetState] = useState("vi");
  const [voice, setVoice] = useState("am_adam"); const [speakTranslation, setSpeakTranslation] = useState(true);
  const [hotkey, setHotkey] = useState("ctrl+alt+space"); const [hotkeyCapturing, setHotkeyCapturing] = useState(false); const [hotkeyMicrophones, setHotkeyMicrophones] = useState<string[]>([]); const [hotkeyMicrophone, setHotkeyMicrophone] = useState("__default__"); const [hotkeySource, setHotkeySource] = useState("vi"); const [hotkeyTarget, setHotkeyTarget] = useState("en"); const [hotkeyTranslate, setHotkeyTranslate] = useState(true); const [hotkeyNotice, setHotkeyNotice] = useState("");
  const [glossary, setGlossary] = useState("thanh toán\nhóa đơn\nhoàn tiền\nchuyển khoản\nAPI\nproduction\nstaging");
  const [meetingContext, setMeetingContext] = useState("Cuộc họp công việc và thanh toán. Giữ nguyên tên người, tên sản phẩm, số tiền và ngày tháng.");
  const [outRunning, setOutRunning] = useState(false); const [outPreparing, setOutPreparing] = useState(false); const [outListening, setOutListening] = useState(false); const [outNotice, setOutNotice] = useState(t.readyMic); const [outFeed, setOutFeed] = useState<FeedItem[]>([]); const [level, setLevel] = useState(0);
  const [inRunning, setInRunning] = useState(false); const [inPreparing, setInPreparing] = useState(false); const [inListening, setInListening] = useState(false); const [inNotice, setInNotice] = useState(t.readyOther); const [inFeed, setInFeed] = useState<FeedItem[]>([]);
  const setInSource = useCallback((value: string) => { setInSourceState(value); setInFeed([]); setInNotice(uiLang === "vi" ? `Đã chọn đầu vào ${value.toUpperCase()}` : `Input changed to ${value.toUpperCase()}`); }, [uiLang]);
  const setInTarget = useCallback((value: string) => { setInTargetState(value); setInFeed([]); setInNotice(uiLang === "vi" ? `Đã chọn đầu ra ${value.toUpperCase()}` : `Output changed to ${value.toUpperCase()}`); }, [uiLang]);
  const outWs = useRef<WebSocket | null>(null); const inWs = useRef<WebSocket | null>(null); const streamRef = useRef<MediaStream | null>(null); const contextRef = useRef<AudioContext | null>(null); const processorRef = useRef<ScriptProcessorNode | null>(null);
  const micWatchdogRef = useRef<number | null>(null); const sentFramesRef = useRef(0); const audioQueue = useRef<string[]>([]); const playing = useRef(false);
  const ttsSupported = outTarget === "en" || outTarget === "zh";
  const glossaryItems = useCallback(() => glossary.split("\n").map((item) => item.trim()).filter(Boolean), [glossary]);

  const refreshDevices = useCallback(async () => {
    if (navigator.mediaDevices?.enumerateDevices) {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setMicDevices(devices.filter((d) => d.kind === "audioinput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` })));
      setOutputDevices(devices.filter((d) => d.kind === "audiooutput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Audio output ${i + 1}` })));
    }
    try { const payload = await (await fetch(`${HTTP}/audio-output-devices`)).json(); if (payload.ok) setSpeakerDevices(payload.devices || []); } catch { setSpeakerDevices([]); }
  }, []);

  useEffect(() => {
    let active = true; const check = async () => { try { const response = await fetch(`${HTTP}/health`); if (!response.ok) throw new Error(); if (active) setOnline(true); } catch { if (active) setOnline(false); } };
    void check(); window.setTimeout(() => void refreshDevices(), 0); const timer = window.setInterval(check, 3000); navigator.mediaDevices?.addEventListener("devicechange", refreshDevices);
    return () => { active = false; window.clearInterval(timer); navigator.mediaDevices?.removeEventListener("devicechange", refreshDevices); };
  }, [refreshDevices]);

  useEffect(() => {
    if (!settingsOpen) return;
    void fetch(`${HTTP}/models/status`).then((response) => response.json()).then((payload) => {
      if (payload.ok) { setModelAssets(payload.assets || []); setModelCacheRoot(payload.cache_root || ""); }
    }).catch(() => { setModelAssets([]); setModelCacheRoot(""); });
    void fetch(`${HTTP}/hotkey/settings`).then((response) => response.json()).then((payload) => {
      if (payload.ok) { setHotkey(payload.hotkey || "ctrl+alt+space"); setHotkeyMicrophone(payload.microphone || "__default__"); setHotkeySource(payload.source_language || "vi"); setHotkeyTarget(payload.target_language || "en"); setHotkeyTranslate(Boolean(payload.translate)); }
    }).catch(() => setHotkeyNotice(uiLang === "vi" ? "Không đọc được cấu hình hotkey" : "Could not load hotkey settings"));
    void fetch(`${HTTP}/audio-input-devices`).then((response) => response.json()).then((payload) => { if (payload.ok) setHotkeyMicrophones(payload.devices || []); }).catch(() => setHotkeyMicrophones([]));
  }, [settingsOpen, uiLang]);

  const captureHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();
    const raw = event.key.toLowerCase();
    if (raw === "escape") { setHotkeyCapturing(false); event.currentTarget.blur(); return; }
    if (["control", "shift", "alt", "meta"].includes(raw)) return;
    const aliases: Record<string, string> = { " ": "space", arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right" };
    const parts: string[] = [];
    if (event.ctrlKey) parts.push("ctrl"); if (event.altKey) parts.push("alt"); if (event.shiftKey) parts.push("shift"); if (event.metaKey) parts.push("windows");
    parts.push(aliases[raw] || raw);
    setHotkey(parts.join("+")); setHotkeyCapturing(false); event.currentTarget.blur();
  }, []);

  const saveHotkeySettings = useCallback(async () => {
    setHotkeyNotice(uiLang === "vi" ? "Đang lưu…" : "Saving…");
    try {
      const response = await fetch(`${HTTP}/hotkey/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hotkey, microphone: hotkeyMicrophone, mode, source_language: hotkeySource, target_language: hotkeyTarget, translate: hotkeyTranslate }) });
      if (!response.ok) throw new Error((await response.json()).detail || "Invalid hotkey");
      setHotkeyNotice(t.hotkeySaved);
    } catch (error) { setHotkeyNotice(error instanceof Error ? error.message : "Hotkey error"); }
  }, [hotkey, hotkeyMicrophone, hotkeySource, hotkeyTarget, hotkeyTranslate, mode, t.hotkeySaved, uiLang]);

  const playNext = useCallback(async () => {
    if (playing.current || audioQueue.current.length === 0) return; playing.current = true; const audio = new Audio(audioQueue.current.shift()!); const sink = audio as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> };
    try { if (outputId !== "default" && sink.setSinkId) await sink.setSinkId(outputId); await audio.play(); await new Promise<void>((resolve) => { audio.onended = () => resolve(); audio.onerror = () => resolve(); }); }
    finally { playing.current = false; void playNext(); }
  }, [outputId]);

  const stopOutgoing = useCallback(() => {
    if (micWatchdogRef.current !== null) window.clearTimeout(micWatchdogRef.current); micWatchdogRef.current = null; sentFramesRef.current = 0;
    processorRef.current?.disconnect(); processorRef.current = null; void contextRef.current?.close(); contextRef.current = null; streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null; outWs.current?.close(); outWs.current = null;
    setOutPreparing(false); setOutRunning(false); setOutListening(false); setLevel(0); setOutNotice(COPY[uiLang].stoppedMic);
  }, [uiLang]);

  const startOutgoing = useCallback(async () => {
    if (!online) return setOutNotice(COPY[uiLang].offline);
    try {
      setOutPreparing(true); setOutNotice(COPY[uiLang].preparing); const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext; const context = new AudioContextClass(); contextRef.current = context; await context.resume();
      const [prepareResponse, stream] = await Promise.all([fetch(`${HTTP}/prepare/${mode}`, { method: "POST" }), navigator.mediaDevices.getUserMedia({ audio: { deviceId: micId === "default" ? undefined : { exact: micId }, channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })]);
      if (!prepareResponse.ok) { stream.getTracks().forEach((track) => track.stop()); throw new Error("Model preparation failed"); } streamRef.current = stream; await refreshDevices();
      const socket = new WebSocket(OUT_WS); socket.binaryType = "arraybuffer"; outWs.current = socket;
      socket.onopen = () => { sentFramesRef.current = 0; socket.send(JSON.stringify({ type: "config", mode, voice: outTarget === "zh" ? "zm_yunxi" : voice, glossary: glossaryItems(), meeting_context: meetingContext, source_language: outSource, target_language: outTarget, speak_translation: speakTranslation && ttsSupported })); setOutPreparing(false); setOutRunning(true); setOutNotice(uiLang === "vi" ? "Hãy nói một câu · thanh mức mic phải chuyển động" : "Speak a sentence · the microphone meter should move"); micWatchdogRef.current = window.setTimeout(() => { if (sentFramesRef.current === 0) setOutNotice(uiLang === "vi" ? "Không nhận được âm thanh; hãy chọn lại microphone." : "No audio received; select the correct microphone."); }, 4000); };
      socket.onmessage = (event) => { const message = JSON.parse(event.data); if (message.type === "vad") setOutListening(message.active); if (message.type === "processing") setOutFeed((items) => [{ id: message.id, source: t.recognizing, translation: "", sourceLang: outSource, targetLang: outTarget, state: "processing" }, ...items].slice(0, 100)); if (message.type === "result") { setOutFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: message.source, translation: message.translation, sourceLang: message.source_lang || outSource, targetLang: message.target_lang || outTarget, latencyMs: message.latency_ms, state: "done" } : item)); if (message.audio_base64) { audioQueue.current.push(`data:audio/wav;base64,${message.audio_base64}`); void playNext(); } } if (message.type === "error") { setOutNotice(message.message || "Pipeline error"); if (message.id) setOutFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: uiLang === "vi" ? "Đoạn âm thanh đã được bỏ" : "Audio segment discarded", translation: message.message || "Low confidence", state: "error" } : item)); } if (message.type === "status") setOutNotice(message.message); };
      socket.onclose = () => { setOutPreparing(false); setOutRunning(false); setOutListening(false); }; if (context.state !== "running") await context.resume(); const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1); processorRef.current = processor;
      processor.onaudioprocess = (event) => { const samples = event.inputBuffer.getChannelData(0); let sum = 0; for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i]; setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 6)); if (socket.readyState === WebSocket.OPEN) { socket.send(floatToPcm16(resampleTo16k(samples, context.sampleRate)).buffer); sentFramesRef.current += 1; } };
      const gain = context.createGain(); gain.gain.value = 0; source.connect(processor); processor.connect(gain); gain.connect(context.destination);
    } catch (error) { stopOutgoing(); setOutNotice(error instanceof Error ? error.message : "Microphone error"); }
  }, [glossaryItems, meetingContext, micId, mode, online, outSource, outTarget, playNext, refreshDevices, speakTranslation, stopOutgoing, t, ttsSupported, uiLang, voice]);

  const stopIncoming = useCallback(() => { inWs.current?.close(); inWs.current = null; setInPreparing(false); setInRunning(false); setInListening(false); setInNotice(COPY[uiLang].stoppedOther); }, [uiLang]);
  const startIncoming = useCallback(async () => {
    if (!online) return setInNotice(COPY[uiLang].offline);
    try { setInPreparing(true); setInNotice(COPY[uiLang].preparing); if (!(await fetch(`${HTTP}/prepare/${mode}`, { method: "POST" })).ok) throw new Error("Model preparation failed"); const socket = new WebSocket(IN_WS); inWs.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: "config", mode, device: speakerDevice, glossary: glossaryItems(), meeting_context: meetingContext, source_language: inSource, target_language: inTarget }));
      socket.onmessage = (event) => { const message = JSON.parse(event.data); if (message.type === "vad") setInListening(message.active); if (message.type === "status") { setInPreparing(false); setInRunning(true); setInNotice(message.message); } if (message.type === "processing") setInFeed((items) => [{ id: message.id, source: t.recognizing, translation: "", sourceLang: inSource, targetLang: inTarget, state: "processing" }, ...items].slice(0, 100)); if (message.type === "result") setInFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: message.source, translation: message.translation, sourceLang: message.source_lang || inSource, targetLang: inTarget, latencyMs: message.latency_ms, state: "done" } : item)); if (message.type === "error") { setInPreparing(false); setInNotice(message.message || "Pipeline error"); if (message.id) setInFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: uiLang === "vi" ? "Đoạn âm thanh đã được bỏ" : "Audio segment discarded", translation: message.message || "Low confidence", state: "error" } : item)); } };
      socket.onclose = () => { setInPreparing(false); setInRunning(false); setInListening(false); };
    } catch (error) { stopIncoming(); setInNotice(error instanceof Error ? error.message : "System audio error"); }
  }, [glossaryItems, inSource, inTarget, meetingContext, mode, online, speakerDevice, stopIncoming, t, uiLang]);

  const exportDoc = (items: FeedItem[], title: string) => {
    const rows = [...items].reverse().filter((item) => item.state === "done").map((item) => `<tr><td><b>${escapeHtml(item.sourceLang.toUpperCase())}</b><br>${escapeHtml(item.source)}</td><td><b>${escapeHtml(item.targetLang.toUpperCase())}</b><br>${escapeHtml(item.translation)}</td></tr>`).join("");
    const html = `<html><head><meta charset="utf-8"><style>body{font-family:Arial}table{border-collapse:collapse;width:100%}td{border:1px solid #bbb;padding:10px;vertical-align:top}</style></head><body><h1>${escapeHtml(title)}</h1><p>${new Date().toLocaleString()}</p><table>${rows}</table></body></html>`;
    const url = URL.createObjectURL(new Blob([html], { type: "application/msword;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `SpeakBridge-${title.replace(/\W+/g, "-")}-${new Date().toISOString().slice(0, 10)}.doc`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const anyRunning = outRunning || inRunning;
  const transcriptBoard = (kind: "incoming" | "outgoing", items: FeedItem[], sourceCode: string, targetCode: string, listening: boolean) => {
    const incoming = kind === "incoming"; const number = incoming ? "02A" : "02B"; const title = `${incoming ? (uiLang === "vi" ? "Bên kia nói" : "Remote side") : (uiLang === "vi" ? "Tôi nói" : "My voice")} → ${languageName(targetCode, uiLang)}`;
    return <section className={`transcriptBoard ${incoming ? "incomingBoard" : "outgoingBoard"} ${listening ? "live" : ""}`}><div className="panelHeader"><div className="sectionTitle"><span>{number}</span><h2>{title}</h2></div><div className="panelActions"><button onClick={() => exportDoc(items, number)} disabled={!items.some((item) => item.state === "done")}>{t.export}</button><button onClick={() => incoming ? setInFeed([]) : setOutFeed([])} disabled={!items.length}>↻ {t.clear}</button></div></div><div className="boardLanguageGrid"><label><span>IN</span><LanguageSelect value={sourceCode} onChange={incoming ? setInSource : setOutSource} allowAuto disabled={incoming ? inRunning : outRunning} /></label><b>→</b><label><span>OUT</span><LanguageSelect value={targetCode} onChange={incoming ? setInTarget : setOutTarget} disabled={incoming ? inRunning : outRunning} /></label></div><div className="legend languageLegend"><i className="sourceDot" />{sourceCode.toUpperCase()} <i className={incoming ? "viDot" : "enDot"} />{targetCode.toUpperCase()}</div><div className="feed">{items.length === 0 ? <div className="emptyState"><span>⌁</span><h3>{incoming ? t.emptyOther : t.emptyMe}</h3></div> : items.map((item) => <article key={item.id} className={`feedItem ${item.state}`}><div className="language sourceLanguage"><span>{item.sourceLang.toUpperCase()}</span><p>{item.source}</p></div><div className="language targetLanguage"><span>{item.targetLang.toUpperCase()}</span><p>{item.translation || (item.state === "processing" ? t.translating : "—")}</p></div>{item.latencyMs !== undefined && <small>{(item.latencyMs / 1000).toFixed(1)}s</small>}</article>)}</div></section>;
  };

  return <main className="shell">
    <header className="topbar"><div className="brand"><span className="brandMark">S</span><div><strong>SpeakBridge V2</strong><small>{t.twoWay}</small></div></div><div className="headerActions"><div className={`health ${online ? "online" : "offline"}`}><span />{online ? t.online : t.offline}</div><button className="settingsButton" onClick={() => setSettingsOpen(true)}>⚙ {t.settings}</button></div></header>
    <section className="hero compactHero"><div><p className="eyebrow">{t.eyebrow}</p><h1>{t.heroA}<br /><em>{t.heroB}</em></h1><p className="lead">{t.lead}</p></div><div className={`orb ${anyRunning ? "active" : ""} ${outListening || inListening ? "speaking" : ""}`} style={{ "--level": level } as React.CSSProperties}><div className="orbCore"><span>{anyRunning ? "LIVE" : "READY"}</span><b>{inRunning && outRunning ? "↔ LIVE" : "LOCAL"}</b></div></div></section>
    <section className="workspace v2Workspace"><aside className="controlPanel"><div className="sectionTitle"><span>01</span><h2>{t.controls}</h2></div>
      <div className="controlGroup"><h3>{t.myVoice}</h3><label className="field"><span>{t.microphone}</span><select value={micId} onChange={(e) => setMicId(e.target.value)} disabled={outRunning}><option value="default">{t.defaultMic}</option>{micDevices.filter((d) => d.deviceId !== "default").map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}</select></label>
        <div className="languageGrid"><label className="field"><span>{t.sourceLanguage}</span><LanguageSelect value={outSource} onChange={setOutSource} allowAuto disabled={outRunning} /></label><label className="field"><span>{t.targetLanguage}</span><LanguageSelect value={outTarget} onChange={(value) => { setOutTarget(value); if (value === "zh") setVoice("zm_yunxi"); else if (voice === "zm_yunxi") setVoice("am_adam"); }} disabled={outRunning} /></label></div>
        <label className="field"><span>{t.ttsOutput}</span><select value={outputId} onChange={(e) => setOutputId(e.target.value)} disabled={outRunning}><option value="default">{t.defaultSpeaker}</option>{outputDevices.filter((d) => d.deviceId !== "default").map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}</select><small className={outputId === "default" ? "routingWarning" : ""}>{outputId === "default" ? t.routeWarn : t.routeOk}</small></label>
        {outTarget === "en" && <label className="field"><span>{t.voice}</span><select value={voice} onChange={(e) => setVoice(e.target.value)} disabled={outRunning}><option value="am_adam">US Male · Adam</option><option value="am_michael">US Male · Michael</option><option value="bm_george">UK Male · George</option><option value="bm_lewis">UK Male · Lewis</option><option value="af_heart">US Female · Heart</option></select></label>}
        {outTarget === "zh" && <label className="field"><span>{t.voice}</span><select value="zm_yunxi" disabled><option value="zm_yunxi">中文男声 · Yunxi</option></select></label>}
        <label className="checkField"><input type="checkbox" checked={speakTranslation && ttsSupported} onChange={(e) => setSpeakTranslation(e.target.checked)} disabled={!ttsSupported || outRunning} /><span>{t.speak}</span></label>{!ttsSupported && <p className="routingWarning inlineWarning">{t.textOnly}</p>}
        <button className={`startButton ${outRunning ? "stop" : ""}`} onClick={outRunning ? stopOutgoing : startOutgoing} disabled={outPreparing}><span>{outRunning ? "■" : outPreparing ? "◌" : "●"}</span>{outRunning ? t.stopMic : outPreparing ? t.preparing : t.startMe}</button><div className="micMeter"><span style={{ width: `${Math.max(2, level * 100)}%` }} /></div><p className="notice">{outNotice}</p>
      </div>
      <div className="controlGroup incomingControls"><h3>{t.otherSide}</h3><div className="languageGrid"><label className="field"><span>{t.sourceLanguage}</span><LanguageSelect value={inSource} onChange={setInSource} allowAuto disabled={inRunning} /></label><label className="field"><span>{t.targetLanguage}</span><LanguageSelect value={inTarget} onChange={setInTarget} disabled={inRunning} /></label></div>
        <label className="field"><span>{t.playbackDevice}</span><select value={speakerDevice} onChange={(e) => setSpeakerDevice(e.target.value)} disabled={inRunning}><option value="__default__">{t.defaultPlayback}</option>{speakerDevices.map((device) => <option key={device} value={device}>{device}</option>)}</select><small>{t.playbackHelp}</small></label><button className={`startButton secondary ${inRunning ? "stop" : ""}`} onClick={inRunning ? stopIncoming : startIncoming} disabled={inPreparing}><span>{inRunning ? "■" : inPreparing ? "◌" : "●"}</span>{inRunning ? t.stopOther : inPreparing ? t.preparing : t.startOther}</button><p className="notice">{inNotice}</p>
      </div>
      <div className="field"><span>{t.mode}</span><div className="modeSwitch"><button className={mode === "fast" ? "selected" : ""} onClick={() => setMode("fast")} disabled={anyRunning}>FAST<small>Turbo · low latency</small></button><button className={mode === "quality" ? "selected" : ""} onClick={() => setMode("quality")} disabled={anyRunning}>QUALITY<small>Large-v3 · beam 5</small></button></div></div>
      <label className="field"><span>{t.context}</span><textarea value={meetingContext} onChange={(e) => setMeetingContext(e.target.value)} disabled={anyRunning} /><small>{t.contextHelp}</small></label><label className="field glossary"><span>{t.glossary}</span><textarea value={glossary} onChange={(e) => setGlossary(e.target.value)} disabled={anyRunning} /><small>{t.glossaryHelp}</small></label>
    </aside><section className="dualTranscript">{transcriptBoard("incoming", inFeed, inSource, inTarget, inListening)}{transcriptBoard("outgoing", outFeed, outSource, outTarget, outListening)}</section></section>
    <footer><span>Whisper · Hy-MT2 7B · Kokoro · WASAPI</span><span>VI / EN / ZH verified · English/Chinese local TTS</span></footer>
    {settingsOpen && <div className="settingsOverlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false); }}><section className="settingsDialog"><div className="settingsHead"><h2>⚙ {t.settings}</h2><button onClick={() => setSettingsOpen(false)}>×</button></div><label className="field"><span>{t.uiLanguage}</span><select value={uiLang} onChange={(e) => setUiLang(e.target.value as UiLanguage)}><option value="vi">Tiếng Việt</option><option value="en">English</option></select></label><label className="field"><span>{t.translator}</span><select value="hy-mt2" disabled><option value="hy-mt2">Hy-MT2 7B Q6 · Recommended</option></select><small>FAST / QUALITY changes Whisper ASR; Hy-MT2 is shared by both streams.</small></label><div className="hotkeySettings"><h3>{t.hotkeyTitle}</h3><p>{t.hotkeyHelp}</p><label className={`field hotkeyCapture ${hotkeyCapturing ? "capturing" : ""}`}><span>{t.hotkeyLabel}</span><input value={hotkeyCapturing ? t.hotkeyCapture : hotkey} readOnly onFocus={() => setHotkeyCapturing(true)} onClick={() => setHotkeyCapturing(true)} onKeyDown={captureHotkey} /></label><label className="field"><span>{t.hotkeyMic}</span><select value={hotkeyMicrophone} onChange={(e) => setHotkeyMicrophone(e.target.value)}><option value="__default__">{t.defaultMic}</option>{hotkeyMicrophones.map((device) => <option key={device} value={device}>{device}</option>)}</select><small>{uiLang === "vi" ? "Hãy chọn USB Condenser; không chọn CABLE Output." : "Select the USB condenser microphone; do not select CABLE Output."}</small></label><div className="languageGrid"><label className="field"><span>{t.sourceLanguage}</span><LanguageSelect value={hotkeySource} onChange={setHotkeySource} allowAuto /></label><label className="field"><span>{t.targetLanguage}</span><LanguageSelect value={hotkeyTarget} onChange={setHotkeyTarget} disabled={!hotkeyTranslate} /></label></div><label className="checkField"><input type="checkbox" checked={hotkeyTranslate} onChange={(e) => setHotkeyTranslate(e.target.checked)} /><span>{t.hotkeyTranslate}</span></label><button className="startButton secondary" onClick={saveHotkeySettings}>{t.hotkeySave}</button>{hotkeyNotice && <p className="notice">{hotkeyNotice}</p>}</div><div className="modelStatus"><h3>{uiLang === "vi" ? "Model local đã cài" : "Installed local models"}</h3>{modelAssets.map((asset) => <article key={asset.name}><span className={asset.installed ? "installed" : "missing"}>{asset.installed ? "✓" : "!"}</span><div><b>{asset.name}</b><small>{asset.role} · {asset.processor} · {asset.size_gb} GB</small><code title={asset.path}>{asset.path}</code></div></article>)}<p>{uiLang === "vi" ? "Cache cố định:" : "Pinned cache:"} <code>{modelCacheRoot || "—"}</code></p><small>{uiLang === "vi" ? "Không cần tải model riêng theo ngôn ngữ: Whisper và Hy-MT2 là model đa ngôn ngữ. UI chỉ hiện VI/EN/ZH vì đây là ba ngôn ngữ đã kiểm thử end-to-end." : "No per-language model is required: Whisper and Hy-MT2 are multilingual. The UI shows VI/EN/ZH because these are end-to-end verified."}</small></div><p className="storageNote">{t.storage}</p><button className="startButton" onClick={() => setSettingsOpen(false)}>{t.close}</button></section></div>}
  </main>;
}
