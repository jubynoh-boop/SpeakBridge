"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { shortcutFromEvent } from "../lib/hotkeys";
import { SpeechPlayer } from "../lib/speech-player";
import { VideoDubPanel } from "../lib/video-dub-panel";

type State = "processing" | "done" | "error";
type FeedItem = { id: string; source: string; translation: string; sourceLang: string; targetLang: string; latencyMs?: number; createdAt?: number; state: State };
type DeviceOption = { deviceId: string; label: string };
type ModelAsset = { name: string; role: string; processor: string; installed: boolean; size_gb: number; path: string; missing_files: string[] };
type VoiceOption = { id: string; label: string; installed: boolean; error: string };
type UiLanguage = "vi" | "en";
type ScreenRegion = { x: number; y: number; width: number; height: number };
type ScreenOverlay = ScreenRegion & { source: string; translation: string };
type AdvisorSuggestion = { title: string; answer: string; reason: string; sources: string[]; confidence: number };
type AdvisorDocument = { id: string; name: string; category: "knowledge" | "meeting_log"; created_at: string; characters: number; chunks: number };

const HTTP = "http://127.0.0.1:8765";
const OUT_WS = "ws://127.0.0.1:8765/ws/audio";
const IN_WS = "ws://127.0.0.1:8765/ws/system-audio";

const LANGUAGES = [
  ["vi", "Tiếng Việt", "Vietnamese"], ["en", "Tiếng Anh", "English"], ["zh", "Tiếng Trung", "Chinese"],
  ["ja", "Tiếng Nhật", "Japanese"], ["ko", "Tiếng Hàn", "Korean"],
] as const;

const ADVISOR_PROVIDERS: Record<string, { label: string; baseUrl: string; model: string }> = {
  openai: { label: "OpenAI API", baseUrl: "https://api.openai.com/v1", model: "gpt-6-luna" },
  anthropic: { label: "Anthropic Claude", baseUrl: "https://api.anthropic.com/v1", model: "" },
  deepseek: { label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  "9router": { label: "9Router", baseUrl: "http://127.0.0.1:20128/v1", model: "auto" },
  custom: { label: "Custom OpenAI-compatible", baseUrl: "http://127.0.0.1:11434/v1", model: "" },
};

const COPY = {
  vi: {
    twoWay: "Hai chiều · Local AI", online: "Local engine online", offline: "Backend offline", settings: "Cài đặt",
    eyebrow: "PHIÊN DỊCH HỌP HAI CHIỀU", heroA: "Nghe bên kia bằng ngôn ngữ của bạn.", heroB: "Nói ra ngôn ngữ họ cần.",
    lead: "Mỗi luồng có ngôn ngữ vào/ra riêng. Âm thanh bên kia chỉ tạo phụ đề; giọng của bạn có thể phát qua VB-CABLE.",
    controls: "Điều khiển hai luồng", myVoice: "Tôi nói → dịch + giọng đọc", microphone: "Microphone", defaultMic: "Microphone mặc định",
    ttsOutput: "Đầu ra giọng dịch", defaultSpeaker: "Loa mặc định", routeWarn: "Loa mặc định có thể bị 02A thu lại. Khi họp hãy chọn CABLE Input.",
    routeOk: "Meet chọn mic CABLE Output; loa Meet và 02A vẫn chọn tai nghe thật.", sourceLanguage: "Ngôn ngữ nói", targetLanguage: "Ngôn ngữ dịch",
    voice: "Giọng đọc", speak: "Phát giọng dịch", textOnly: "Ngôn ngữ này hiện chỉ có phụ đề; TTS local hỗ trợ Việt, Anh, Trung, Nhật và Hàn.",
    startMe: "Bắt đầu tôi nói", stopMic: "Dừng microphone", preparing: "Đang chuẩn bị…", otherSide: "Bên kia → phụ đề",
    playbackDevice: "Thiết bị đang phát Meet / Discord / YouTube", defaultPlayback: "Thiết bị phát mặc định Windows",
    playbackHelp: "Chọn tai nghe/loa thật đang phát tiếng bên kia; không chọn CABLE Input/In 16ch.", startOther: "Bắt đầu nghe bên kia", stopOther: "Dừng nghe bên kia",
    mode: "Chế độ dùng chung", context: "Ngữ cảnh cuộc họp", contextHelp: "Có tác dụng thật: gửi vào cả Whisper và Hy-MT2. Viết 1–3 câu mô tả chủ đề, ví dụ thanh toán, y tế hoặc kỹ thuật.", glossary: "Hotwords / Glossary",
    glossaryHelp: "Có tác dụng thật: mỗi dòng là một tên riêng hoặc thuật ngữ Whisper cần ưu tiên và giữ đúng cách viết.", auto: "Tự nhận diện", export: "Xuất .doc", clear: "Xóa lịch sử",
    emptyOther: "Phụ đề bên kia xuất hiện tại đây", emptyMe: "Bản dịch giọng bạn xuất hiện tại đây", recognizing: "Đang nhận dạng…", translating: "Đang dịch…",
    uiLanguage: "Ngôn ngữ giao diện", translator: "Model dịch", storage: "Lịch sử chỉ nằm trong RAM và mất khi tải lại; không làm ổ đĩa phình to.", close: "Đóng",
    hotkeyTitle: "Voice Typing toàn Windows", hotkeyHelp: "Đặt con trỏ vào ô nhập, giữ phím tắt để nói rồi thả ra. Helper sẽ nhận dạng hoặc dịch và dán chữ; không tự nhấn Enter.", hotkeyLabel: "Phím tắt giữ để nói", textHotkeyLabel: "Phím tắt dịch chữ trong ô chat", textHotkeyHelp: "Bôi đen một đoạn để chỉ dịch đoạn đó; nếu không bôi đen, SpeakBridge dịch toàn bộ nội dung ô nhập rồi thay bằng bản dịch.", hotkeyCapture: "Nhấp vào đây rồi bấm tổ hợp phím", hotkeyMic: "Microphone Voice Typing", hotkeyTranslate: "Dịch trước khi nhập", hotkeySave: "Lưu cấu hình hotkey", hotkeySaved: "Đã lưu · helper tự cập nhật trong vài giây", desktopScreenHotkeyTitle: "Dịch vùng trên desktop", desktopScreenHotkeyHelp: "Đặt chuột ở màn hình cần dịch, nhấn phím nóng rồi kéo vùng. Overlay live cập nhật subtitle cho đến khi bấm phím thoát.", desktopScreenHotkeyLabel: "Phím tắt chọn vùng", desktopExitHotkey: "Phím thoát bản dịch", desktopContinuous: "Dịch liên tục vùng đã chọn (video/subtitle)", desktopRefresh: "Chu kỳ quét tối thiểu (giây)", desktopOpacity: "Độ mờ overlay", desktopFontSize: "Cỡ chữ overlay (px)", desktopShowStatus: "Hiện thanh trạng thái SpeakBridge trên màn hình",
    screenReadTitle: "Đọc chữ đã bôi đen", screenReadHelp: "Dùng chuột bôi đen chữ có thể sao chép, rồi bấm phím tắt. App đọc đúng đoạn đã chọn qua loa/tai nghe đã chọn; không chụp màn hình hay mở khung OCR.", screenReadHotkey: "Phím tắt đọc chữ đã chọn", screenReadMode: "Nội dung được đọc", screenReadSource: "Ngôn ngữ chữ đã chọn", screenReadTarget: "Dịch và đọc bằng", screenReadOriginal: "Đọc chữ gốc", screenReadTranslation: "Dịch rồi đọc", screenReadProcessor: "Trang/ứng dụng phải cho phép sao chép chữ bôi đen. Chữ nằm trong ảnh hoặc video cần dùng OCR riêng ở mục 03.",
    readyMic: "Sẵn sàng nhận microphone", readyOther: "Sẵn sàng nghe Meet / Discord", stoppedMic: "Đã dừng microphone", stoppedOther: "Đã dừng nghe bên kia",
    screenTitle: "Dịch chữ trên màn hình", screenHelp: "Chọn tab Bilibili, cửa sổ video hoặc tài liệu. Bản dịch sẽ đè đúng vị trí chữ trên ảnh.", screenProcessor: "Bộ xử lý OCR", screenCpu: "CPU · ít VRAM", screenGpu: "GPU · nhanh hơn", screenStart: "Chọn màn hình để dịch", screenStop: "Dừng dịch màn hình", screenEmpty: "Bản dịch chữ trên màn hình sẽ xuất hiện tại đây", screenReset: "Chọn lại vùng", screenSelecting: "Kéo chuột trên ảnh để khoanh vùng cần dịch", screenWatching: "Đang dịch và đặt chữ đúng vị trí", screenNoText: "Chưa tìm thấy chữ trong vùng đã chọn", screenAreaMode: "Vùng cần dịch", screenRegionMode: "KHOANH VÙNG", screenFullMode: "TOÀN ẢNH", screenFullscreen: "Xem ảnh dịch toàn màn hình", screenExitFullscreen: "Thoát toàn màn hình",
    advisorTitle: "AI gợi ý trả lời", advisorEmpty: "Gợi ý sẽ xuất hiện sau khi khách ngừng nói", advisorEnabled: "Bật trợ lý tư vấn", dealMode: "Gợi ý deal mềm", strictScope: "Chỉ tư vấn trong tài liệu", advisorThinking: "Đang đọc context và tài liệu…", advisorDocs: "Tài liệu kiến thức", uploadDoc: "Thêm tài liệu", saveAdvisor: "Lưu trợ lý", testApi: "Kiểm tra API", copyAnswer: "Sao chép", followUp: "Câu hỏi nên hỏi tiếp", silenceDelay: "Kích hoạt gợi ý", apiProvider: "Nhà cung cấp AI", apiModel: "Model / alias", apiBase: "Base URL", apiKey: "API key",
  },
  en: {
    twoWay: "Two-way · Local AI", online: "Local engine online", offline: "Backend offline", settings: "Settings",
    eyebrow: "TWO-WAY MEETING INTERPRETER", heroA: "Hear them in your language.", heroB: "Speak in the language they need.",
    lead: "Each stream has independent input/output languages. Remote audio produces subtitles; your translated voice can be routed through VB-CABLE.",
    controls: "Two-stream controls", myVoice: "My voice → translation + speech", microphone: "Microphone", defaultMic: "Default microphone",
    ttsOutput: "Translated voice output", defaultSpeaker: "Default speaker", routeWarn: "The default speaker may be captured by 02A. Select CABLE Input during calls.",
    routeOk: "Meet microphone: CABLE Output; Meet speaker and 02A: physical headphones.", sourceLanguage: "Spoken language", targetLanguage: "Translation language",
    voice: "Voice", speak: "Play translated speech", textOnly: "This language is subtitle-only; local TTS supports Vietnamese, English, Chinese, Japanese and Korean.",
    startMe: "Start my microphone", stopMic: "Stop microphone", preparing: "Preparing…", otherSide: "Remote side → subtitles",
    playbackDevice: "Device playing Meet / Discord / YouTube", defaultPlayback: "Windows default playback device",
    playbackHelp: "Select the physical headphones/speakers playing the remote side; do not select CABLE Input/In 16ch.", startOther: "Start remote listening", stopOther: "Stop remote listening",
    mode: "Shared mode", context: "Meeting context", contextHelp: "Active in the backend: sent to both Whisper and Hy-MT2. Write 1–3 sentences describing the meeting topic.", glossary: "Hotwords / Glossary",
    glossaryHelp: "Active in the backend: one proper name or technical term per line for Whisper priority and exact casing.", auto: "Auto detect", export: "Export .doc", clear: "Clear history",
    emptyOther: "Remote subtitles will appear here", emptyMe: "Your translated speech will appear here", recognizing: "Recognizing…", translating: "Translating…",
    uiLanguage: "Interface language", translator: "Translation model", storage: "History stays in RAM and is cleared on reload; it does not grow disk usage.", close: "Close",
    hotkeyTitle: "Windows-wide Voice Typing", hotkeyHelp: "Focus a text field, hold the shortcut while speaking, then release. The helper transcribes or translates and pastes text without pressing Enter.", hotkeyLabel: "Push-to-talk shortcut", textHotkeyLabel: "Translate typed text shortcut", textHotkeyHelp: "Select text to translate only that part; with no selection, SpeakBridge translates and replaces the entire focused input.", hotkeyCapture: "Click here, then press the key combination", hotkeyMic: "Voice Typing microphone", hotkeyTranslate: "Translate before typing", hotkeySave: "Save hotkey settings", hotkeySaved: "Saved · helper reloads within a few seconds", desktopScreenHotkeyTitle: "Desktop region translation", desktopScreenHotkeyHelp: "Place the pointer on the target monitor, press the shortcut, then drag. The live overlay updates subtitles until you press the exit shortcut.", desktopScreenHotkeyLabel: "Region selection shortcut", desktopExitHotkey: "Translation exit shortcut", desktopContinuous: "Continuously translate the selected video/subtitle region", desktopRefresh: "Minimum scan interval (seconds)", desktopOpacity: "Overlay opacity", desktopFontSize: "Overlay font size (px)", desktopShowStatus: "Show SpeakBridge status bar on screen",
    screenReadTitle: "Read highlighted text aloud", screenReadHelp: "Highlight copyable text with the mouse, then press the shortcut. SpeakBridge reads only that selection through your selected speaker/headphones; no screenshot or OCR selection box.", screenReadHotkey: "Read selection shortcut", screenReadMode: "What to read", screenReadSource: "Selected text language", screenReadTarget: "Translate and read in", screenReadOriginal: "Read original text", screenReadTranslation: "Translate, then read", screenReadProcessor: "The app must allow copying highlighted text. For text embedded in images or videos, use screen OCR in panel 03.",
    readyMic: "Microphone ready", readyOther: "Ready for Meet / Discord audio", stoppedMic: "Microphone stopped", stoppedOther: "Remote listening stopped",
    screenTitle: "On-screen text translation", screenHelp: "Choose a Bilibili tab, video window, or document. Translations are overlaid at the original text positions.", screenProcessor: "OCR processor", screenCpu: "CPU · low VRAM", screenGpu: "GPU · faster", screenStart: "Choose a screen to translate", screenStop: "Stop screen translation", screenEmpty: "On-screen translation will appear here", screenReset: "Reselect area", screenSelecting: "Drag on the image to select the translation area", screenWatching: "Translating text at its on-screen position", screenNoText: "No text found in the selected region yet", screenAreaMode: "Translation area", screenRegionMode: "SELECT AREA", screenFullMode: "FULL IMAGE", screenFullscreen: "View translated image fullscreen", screenExitFullscreen: "Exit fullscreen",
    advisorTitle: "AI reply suggestions", advisorEmpty: "Suggestions appear after the customer stops speaking", advisorEnabled: "Enable advisor", dealMode: "Soft-deal suggestions", strictScope: "Stay within uploaded sources", advisorThinking: "Reading context and sources…", advisorDocs: "Knowledge documents", uploadDoc: "Add document", saveAdvisor: "Save advisor", testApi: "Test API", copyAnswer: "Copy", followUp: "Suggested follow-up", silenceDelay: "Suggestion trigger", apiProvider: "AI provider", apiModel: "Model / alias", apiBase: "Base URL", apiKey: "API key",
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

function escapeHtml(value: string) { return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!)); }

function feedTime(item: FeedItem) {
  const numericId = Number.parseInt(item.id, 10);
  const timestamp = item.createdAt || (Number.isFinite(numericId) && numericId > 1_000_000_000_000 ? numericId : Date.now());
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function LanguageSelect({ value, onChange, allowAuto = false, disabled = false }: { value: string; onChange: (value: string) => void; allowAuto?: boolean; disabled?: boolean }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>{allowAuto && <option value="auto">AUTO · Tự nhận diện</option>}{LANGUAGES.map(([code, vi, en]) => <option key={code} value={code}>{vi} · {en}</option>)}</select>;
}

function FittedScreenOverlay({ overlay, fontSize, foreground, background, opacity }: { overlay: ScreenOverlay; fontSize: number; foreground: string; background: string; opacity: number }) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);

  useLayoutEffect(() => {
    const box = boxRef.current; const text = textRef.current;
    if (!box || !text) return;
    const fit = () => {
      const availableWidth = Math.max(1, box.clientWidth - 4);
      const availableHeight = Math.max(1, box.clientHeight - 2);
      const originalSize = Math.max(5, Math.min(fontSize, availableHeight * 0.92));
      text.style.fontSize = `${originalSize}px`;
      const measuredWidth = Math.max(1, text.getBoundingClientRect().width);
      const fittedSize = Math.max(4, Math.min(originalSize, originalSize * availableWidth / measuredWidth));
      text.style.fontSize = `${fittedSize}px`;
    };
    fit();
    const observer = new ResizeObserver(fit); observer.observe(box);
    return () => observer.disconnect();
  }, [overlay.translation, fontSize]);

  return <div ref={boxRef} className="screenTranslationOverlay" title={overlay.source} style={{ left: `${overlay.x * 100}%`, top: `${overlay.y * 100}%`, width: `${overlay.width * 100}%`, height: `${overlay.height * 100}%`, color: foreground, background: `${background}${Math.round(opacity * 255).toString(16).padStart(2, "0")}` }}><span ref={textRef}>{overlay.translation}</span></div>;
}

function AudioMeter({ value, label }: { value: number; label: string }) {
  const strength = Math.max(0, Math.min(1, value));
  return <span className="measuredWave" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(strength * 100)} title={`${label}: ${Math.round(strength * 100)}%`}>
    {[0.45, 0.75, 1, 0.7, 0.5].map((weight, index) => <i key={index} style={{ height: `${2 + 22 * strength * weight}px`, opacity: strength > 0.015 ? 1 : 0.3 }} />)}
  </span>;
}

async function requestScreenStream(): Promise<MediaStream> {
  let expired = false;
  let timer = 0;
  const pending = navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 5, max: 10 } }, audio: false })
    .then((stream) => {
      if (expired) {
        stream.getTracks().forEach((track) => track.stop());
        throw new Error("Screen selection expired");
      }
      return stream;
    });
  try {
    return await Promise.race([
      pending,
      new Promise<MediaStream>((_, reject) => {
        timer = window.setTimeout(() => {
          expired = true;
          reject(new Error("Không chọn tab/cửa sổ để chia sẻ trong 60 giây. Hãy thử lại."));
        }, 60_000);
      }),
    ]);
  } finally { window.clearTimeout(timer); }
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<"live" | "videodub">("live");
  const [engineInfo, setEngineInfo] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  useEffect(() => {
    if (!contextOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>(".contextDialog");
    const controls = () => Array.from(dialog?.querySelectorAll<HTMLElement>("button, textarea:not(:disabled)") || []);
    controls()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextOpen(false);
      if (event.key === "Tab") {
        const elements = controls(); const first = elements[0]; const last = elements.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); previous?.focus(); };
  }, [contextOpen]);
  const [cableInstalled, setCableInstalled] = useState<boolean | null>(null);
  const [inLevel, setInLevel] = useState(0);
  const [ttsLevel, setTtsLevel] = useState(0);
  const [overlayForeground, setOverlayForeground] = useState("#ffffff");
  const [overlayBackground, setOverlayBackground] = useState("#040806");
  const [draftRegion, setDraftRegion] = useState<ScreenRegion | null>(null);
  const draftRegionRef = useRef<ScreenRegion | null>(null);
  const screenGenerationRef = useRef(0);
  const speechPlayerRef = useRef<SpeechPlayer | null>(null);
  const [voiceOptions, setVoiceOptions] = useState<Record<string, VoiceOption[]>>({});
  const [voiceTesting, setVoiceTesting] = useState(false);
  const [uiLang, setUiLang] = useState<UiLanguage>("vi"); const t = COPY[uiLang];
  const [settingsOpen, setSettingsOpen] = useState(false); const [modelAssets, setModelAssets] = useState<ModelAsset[]>([]); const [modelCacheRoot, setModelCacheRoot] = useState(""); const [ttsLanguages, setTtsLanguages] = useState<string[]>(["en", "zh"]); const [online, setOnline] = useState(false); const [mode, setMode] = useState<"fast" | "quality">("fast");
  const [micDevices, setMicDevices] = useState<DeviceOption[]>([]); const [outputDevices, setOutputDevices] = useState<DeviceOption[]>([]); const [speakerDevices, setSpeakerDevices] = useState<string[]>([]);
  const [micId, setMicId] = useState("default"); const [outputId, setOutputId] = useState("default"); const [speakerDevice, setSpeakerDevice] = useState("__default__");
  const [outSource, setOutSource] = useState("vi"); const [outTarget, setOutTarget] = useState("en"); const [inSource, setInSourceState] = useState("auto"); const [inTarget, setInTargetState] = useState("vi");
  const [voice, setVoice] = useState("am_adam"); const [speakTranslation, setSpeakTranslation] = useState(true);
  const [hotkey, setHotkey] = useState("ctrl+alt+space"); const [hotkeyCapturing, setHotkeyCapturing] = useState(false); const [textTranslateHotkey, setTextTranslateHotkey] = useState("f8"); const [textHotkeyCapturing, setTextHotkeyCapturing] = useState(false); const [textSource, setTextSource] = useState("vi"); const [textTarget, setTextTarget] = useState("en"); const [hotkeyMicrophones, setHotkeyMicrophones] = useState<string[]>([]); const [hotkeyMicrophone, setHotkeyMicrophone] = useState("__default__"); const [hotkeySource, setHotkeySource] = useState("vi"); const [hotkeyTarget, setHotkeyTarget] = useState("en"); const [hotkeyTranslate, setHotkeyTranslate] = useState(true);
  const [desktopScreenHotkey, setDesktopScreenHotkey] = useState("ctrl+alt+t"); const [desktopScreenHotkeyCapturing, setDesktopScreenHotkeyCapturing] = useState(false); const [desktopExitHotkey, setDesktopExitHotkey] = useState("esc"); const [desktopExitHotkeyCapturing, setDesktopExitHotkeyCapturing] = useState(false); const [desktopScreenContinuous, setDesktopScreenContinuous] = useState(true); const [desktopRefreshSeconds, setDesktopRefreshSeconds] = useState(1); const [desktopOverlayOpacity, setDesktopOverlayOpacity] = useState(0.92); const [desktopScreenFontSize, setDesktopScreenFontSize] = useState(14); const [desktopStatusVisible, setDesktopStatusVisible] = useState(true);
  const [screenReadHotkey, setScreenReadHotkey] = useState("ctrl+alt+r"); const [screenReadHotkeyCapturing, setScreenReadHotkeyCapturing] = useState(false); const [screenReadSource, setScreenReadSource] = useState("auto"); const [screenReadTarget, setScreenReadTarget] = useState("vi"); const [screenReadMode, setScreenReadMode] = useState<"source" | "translation">("source");
  const [helperNotice, setHelperNotice] = useState("");
  const [screenReadOutputDevice, setScreenReadOutputDevice] = useState("__default__");
  const [screenReadVoices, setScreenReadVoices] = useState<Record<string, string>>({en:"am_adam", zh:"zm_yunxi", vi:"F1", ja:"F1", ko:"F1"});
  const [screenReadAutoVoiceLanguage, setScreenReadAutoVoiceLanguage] = useState("en");
  const screenReadVoiceLanguage = screenReadMode === "translation" ? screenReadTarget : screenReadSource === "auto" ? screenReadAutoVoiceLanguage : screenReadSource;
  const [screenReadTestNotice, setScreenReadTestNotice] = useState("");
  const [screenReadTestIsVoice, setScreenReadTestIsVoice] = useState(false);
  const [screenReadTesting, setScreenReadTesting] = useState(false);
  const [glossary, setGlossary] = useState("thanh toán\nhóa đơn\nhoàn tiền\nchuyển khoản\nAPI\nproduction\nstaging");
  const [meetingContext, setMeetingContext] = useState("Cuộc họp công việc và thanh toán. Giữ nguyên tên người, tên sản phẩm, số tiền và ngày tháng.");
  const [advisorEnabled, setAdvisorEnabled] = useState(false); const [advisorDeal, setAdvisorDeal] = useState(true); const [advisorStrict, setAdvisorStrict] = useState(true); const [advisorTrigger, setAdvisorTrigger] = useState<"silence" | "sentence">("silence"); const [advisorDelay, setAdvisorDelay] = useState(3);
  const [advisorProvider, setAdvisorProvider] = useState("9router"); const [advisorBaseUrl, setAdvisorBaseUrl] = useState(ADVISOR_PROVIDERS["9router"].baseUrl); const [advisorModel, setAdvisorModel] = useState("auto"); const [advisorApiKey, setAdvisorApiKey] = useState(""); const [advisorHasKey, setAdvisorHasKey] = useState(false);
  const [advisorKnowledgeContext, setAdvisorKnowledgeContext] = useState("");
  const [advisorSuggestions, setAdvisorSuggestions] = useState<AdvisorSuggestion[]>([]); const [advisorFollowUp, setAdvisorFollowUp] = useState(""); const [advisorStatus, setAdvisorStatus] = useState(""); const [advisorLoading, setAdvisorLoading] = useState(false); const [advisorDocs, setAdvisorDocs] = useState<AdvisorDocument[]>([]); const [advisorDocCategory, setAdvisorDocCategory] = useState<"knowledge" | "meeting_log">("knowledge");
  const [outRunning, setOutRunning] = useState(false); const [outPreparing, setOutPreparing] = useState(false); const [outListening, setOutListening] = useState(false); const [outNotice, setOutNotice] = useState<string>(t.readyMic); const [outFeed, setOutFeed] = useState<FeedItem[]>([]); const [level, setLevel] = useState(0);
  const [inRunning, setInRunning] = useState(false); const [inPreparing, setInPreparing] = useState(false); const [inListening, setInListening] = useState(false); const [inNotice, setInNotice] = useState<string>(t.readyOther); const [inFeed, setInFeed] = useState<FeedItem[]>([]);
  const [screenRunning, setScreenRunning] = useState(false); const [screenPreparing, setScreenPreparing] = useState(false); const [screenNotice, setScreenNotice] = useState<string>(t.screenHelp); const [screenProcessor, setScreenProcessor] = useState<"cpu" | "gpu">("cpu"); const [screenActualProcessor, setScreenActualProcessor] = useState("cpu"); const [screenScanElapsed, setScreenScanElapsed] = useState<number | null>(null); const [screenLastLatency, setScreenLastLatency] = useState<number | null>(null);
  const [screenSource, setScreenSource] = useState("zh"); const [screenTarget, setScreenTarget] = useState("vi"); const [screenCaptureMode, setScreenCaptureMode] = useState<"region" | "full">("region"); const [screenRegion, setScreenRegion] = useState<ScreenRegion | null>(null); const [screenOverlays, setScreenOverlays] = useState<ScreenOverlay[]>([]); const [screenFeed, setScreenFeed] = useState<FeedItem[]>([]); const [screenAspectRatio, setScreenAspectRatio] = useState(16 / 9); const [screenFullscreen, setScreenFullscreen] = useState(false);
  const [screenPanelOpen, setScreenPanelOpen] = useState(true); const [screenPanelWidth, setScreenPanelWidth] = useState(42);
  const setInSource = useCallback((value: string) => { setInSourceState(value); setInFeed([]); setInNotice(uiLang === "vi" ? `Đã chọn đầu vào ${value.toUpperCase()}` : `Input changed to ${value.toUpperCase()}`); }, [uiLang]);
  const setInTarget = useCallback((value: string) => { setInTargetState(value); setInFeed([]); setInNotice(uiLang === "vi" ? `Đã chọn đầu ra ${value.toUpperCase()}` : `Output changed to ${value.toUpperCase()}`); }, [uiLang]);
  const outWs = useRef<WebSocket | null>(null); const inWs = useRef<WebSocket | null>(null); const streamRef = useRef<MediaStream | null>(null); const contextRef = useRef<AudioContext | null>(null); const processorRef = useRef<ScriptProcessorNode | null>(null);
  const micWatchdogRef = useRef<number | null>(null); const sentFramesRef = useRef(0);
  const screenStreamRef = useRef<MediaStream | null>(null); const screenVideoRef = useRef<HTMLVideoElement | null>(null); const screenThumbVideoRef = useRef<HTMLVideoElement | null>(null); const screenStageRef = useRef<HTMLDivElement | null>(null); const screenSurfaceRef = useRef<HTMLDivElement | null>(null); const screenCanvasRef = useRef<HTMLCanvasElement | null>(null); const screenLoopRef = useRef<number | null>(null); const screenBusyRef = useRef(false); const screenBusyStartedRef = useRef<number | null>(null); const screenLastFrameRef = useRef(""); const screenLastFrameAtRef = useRef(0); const screenLastTextRef = useRef(""); const screenEmptyFramesRef = useRef(0); const screenDragRef = useRef<{ x: number; y: number } | null>(null); const dashboardRef = useRef<HTMLDivElement | null>(null);
  const advisorTimerRef = useRef<number | null>(null); const advisorGenerationRef = useRef(0); const inFeedRef = useRef<FeedItem[]>([]); const outFeedRef = useRef<FeedItem[]>([]);
  const ttsSupported = ttsLanguages.includes(outTarget);
  const glossaryItems = useCallback(() => glossary.split("\n").map((item) => item.trim()).filter(Boolean), [glossary]);

  const loadAdvisor = useCallback(async () => {
    try {
      const [configPayload, documentsPayload] = await Promise.all([
        fetch(`${HTTP}/advisor/config`).then((response) => response.json()),
        fetch(`${HTTP}/advisor/documents`).then((response) => response.json()),
      ]);
      if (configPayload.ok) { setAdvisorEnabled(Boolean(configPayload.enabled)); setAdvisorDeal(Boolean(configPayload.deal_mode)); setAdvisorStrict(configPayload.strict_scope !== false); setAdvisorTrigger(configPayload.trigger_mode === "sentence" ? "sentence" : "silence"); setAdvisorDelay(Number(configPayload.silence_seconds) || 3); setAdvisorProvider(configPayload.provider || "9router"); setAdvisorBaseUrl(configPayload.base_url || ADVISOR_PROVIDERS["9router"].baseUrl); setAdvisorModel(configPayload.model || "auto"); setAdvisorHasKey(Boolean(configPayload.has_api_key)); setAdvisorKnowledgeContext(configPayload.knowledge_context || ""); }
      if (documentsPayload.ok) setAdvisorDocs(documentsPayload.documents || []);
    } catch { setAdvisorStatus(uiLang === "vi" ? "Không đọc được cấu hình trợ lý" : "Could not load advisor settings"); }
  }, [uiLang]);

  const refreshDevices = useCallback(async () => {
    if (navigator.mediaDevices?.enumerateDevices) {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setMicDevices(devices.filter((d) => d.kind === "audioinput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` })));
      setOutputDevices(devices.filter((d) => d.kind === "audiooutput").map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Audio output ${i + 1}` })));
    }
    try { const payload = await (await fetch(`${HTTP}/audio-output-devices`)).json(); if (payload.ok) { setSpeakerDevices(payload.devices || []); setCableInstalled((payload.devices || []).some((name: string) => /CABLE Input\s*\(VB-Audio/i.test(name))); } } catch { setSpeakerDevices([]); setCableInstalled(null); }
  }, []);

  useEffect(() => {
    let active = true; const check = async () => { try { const response = await fetch(`${HTTP}/health`); if (!response.ok) throw new Error(); const info = await response.json(); if (active) { setOnline(true); setEngineInfo(`ASR ${info.device === "cuda" ? "GPU / CUDA" : "CPU"} · Hy-MT2 ${info.translator === "hy-mt2" ? "ready" : "not ready"}`); } } catch { if (active) { setOnline(false); setEngineInfo(""); } } };
    void check(); window.setTimeout(() => void refreshDevices(), 0); const timer = window.setInterval(check, 3000); navigator.mediaDevices?.addEventListener("devicechange", refreshDevices);
    return () => { active = false; window.clearInterval(timer); navigator.mediaDevices?.removeEventListener("devicechange", refreshDevices); };
  }, [refreshDevices]);

  useEffect(() => {
    void fetch(`${HTTP}/hotkey/settings`).then((response) => response.json()).then((payload) => {
      if (payload.ok) { setOverlayForeground(payload.screen_text_color || "#ffffff"); setOverlayBackground(payload.screen_background_color || "#040806"); setTextTranslateHotkey(payload.text_translate_hotkey || "f8"); setTextSource(payload.text_source_language || "vi"); setTextTarget(payload.text_target_language || "en"); setDesktopScreenHotkey(payload.screen_hotkey || "ctrl+alt+t"); setDesktopExitHotkey(payload.screen_exit_hotkey || "esc"); setDesktopScreenContinuous(payload.screen_continuous !== false); setDesktopRefreshSeconds(Math.max(0.25, Math.min(10, Number(payload.screen_refresh_seconds) || 1))); setDesktopOverlayOpacity(Math.max(0.2, Math.min(1, Number(payload.screen_overlay_opacity) || 0.92))); setDesktopScreenFontSize(Math.max(8, Math.min(48, Number(payload.screen_font_size) || 14))); setDesktopStatusVisible(payload.show_status_overlay !== false); setScreenSource(payload.screen_source_language || "zh"); setScreenTarget(payload.screen_target_language || "vi"); setScreenProcessor(payload.screen_processor === "gpu" ? "gpu" : "cpu"); setScreenReadHotkey(payload.screen_read_hotkey || "ctrl+alt+r"); setScreenReadSource(payload.screen_read_source_language || "auto"); setScreenReadTarget(payload.screen_read_target_language || "vi"); setScreenReadMode(payload.screen_read_mode === "translation" ? "translation" : "source"); setScreenReadOutputDevice(payload.screen_read_output_device || "__default__"); setScreenReadVoices(payload.screen_read_voices || {en:"am_adam", zh:"zm_yunxi", vi:"F1", ja:"F1", ko:"F1"}); }
    }).catch(() => undefined);
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void loadAdvisor(), 0); return () => window.clearTimeout(timer); }, [loadAdvisor]);
  useEffect(() => { inFeedRef.current = inFeed; }, [inFeed]);
  useEffect(() => { outFeedRef.current = outFeed; }, [outFeed]);
  useEffect(() => () => { if (advisorTimerRef.current !== null) window.clearTimeout(advisorTimerRef.current); }, []);

  useEffect(() => {
    const syncFullscreen = () => setScreenFullscreen(document.fullscreenElement === screenStageRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const toggleScreenFullscreen = useCallback(async () => {
    const stage = screenStageRef.current;
    if (!stage) return;
    if (document.fullscreenElement === stage) await document.exitFullscreen();
    else await stage.requestFullscreen();
  }, []);

  useEffect(() => {
    if (!settingsOpen) return;
    void fetch(`${HTTP}/models/status`).then((response) => response.json()).then((payload) => {
      if (payload.ok) { setModelAssets(payload.assets || []); setModelCacheRoot(payload.cache_root || ""); setTtsLanguages(payload.tts_languages || ["en", "zh"]); }
    }).catch(() => { setModelAssets([]); setModelCacheRoot(""); });
    void fetch(`${HTTP}/hotkey/settings`).then((response) => response.json()).then((payload) => {
      if (payload.ok) { setHotkey(payload.hotkey || "ctrl+alt+space"); setTextTranslateHotkey(payload.text_translate_hotkey || "f8"); setTextSource(payload.text_source_language || "vi"); setTextTarget(payload.text_target_language || "en"); setHotkeyMicrophone(payload.microphone || "__default__"); setHotkeySource(payload.source_language || "vi"); setHotkeyTarget(payload.target_language || "en"); setHotkeyTranslate(Boolean(payload.translate)); setDesktopScreenHotkey(payload.screen_hotkey || "ctrl+alt+t"); setDesktopExitHotkey(payload.screen_exit_hotkey || "esc"); setDesktopScreenContinuous(payload.screen_continuous !== false); setDesktopRefreshSeconds(Math.max(0.25, Math.min(10, Number(payload.screen_refresh_seconds) || 1))); setDesktopOverlayOpacity(Math.max(0.2, Math.min(1, Number(payload.screen_overlay_opacity) || 0.92))); setDesktopScreenFontSize(Math.max(8, Math.min(48, Number(payload.screen_font_size) || 14))); setDesktopStatusVisible(payload.show_status_overlay !== false); setScreenSource(payload.screen_source_language || "zh"); setScreenTarget(payload.screen_target_language || "vi"); setScreenProcessor(payload.screen_processor === "gpu" ? "gpu" : "cpu"); setScreenReadHotkey(payload.screen_read_hotkey || "ctrl+alt+r"); setScreenReadSource(payload.screen_read_source_language || "auto"); setScreenReadTarget(payload.screen_read_target_language || "vi"); setScreenReadMode(payload.screen_read_mode === "translation" ? "translation" : "source"); setScreenReadOutputDevice(payload.screen_read_output_device || "__default__"); setScreenReadVoices(payload.screen_read_voices || {en:"am_adam", zh:"zm_yunxi", vi:"F1", ja:"F1", ko:"F1"}); }
    }).catch(() => setHelperNotice(uiLang === "vi" ? "Không đọc được cấu hình hotkey" : "Could not load hotkey settings"));
    void fetch(`${HTTP}/audio-input-devices`).then((response) => response.json()).then((payload) => { if (payload.ok) setHotkeyMicrophones(payload.devices || []); }).catch(() => setHotkeyMicrophones([]));
    void fetch(`${HTTP}/audio-output-devices`).then((response) => response.json()).then((payload) => { if (payload.ok) setSpeakerDevices(payload.devices || []); }).catch(() => setSpeakerDevices([]));
  }, [settingsOpen, uiLang]);

  useEffect(() => {
    void fetch(`${HTTP}/models/status`).then((response) => response.json()).then((payload) => {
      if (payload.ok) setTtsLanguages(payload.tts_languages || ["en", "zh"]);
    }).catch(() => setTtsLanguages(["en", "zh"]));
  }, []);

  const [hotkeyNotices, setHotkeyNotices] = useState<Record<string, string>>({});
  const [modelFolderNotice, setModelFolderNotice] = useState("");
  const hotkeyNoticeVersions = useRef<Record<string, number>>({});
  const markHotkeyDirty = useCallback((section: string) => {
    hotkeyNoticeVersions.current[section] = (hotkeyNoticeVersions.current[section] || 0) + 1;
    setHotkeyNotices((previous) => ({ ...previous, [section]: uiLang === "vi" ? "Có thay đổi chưa lưu." : "Unsaved changes." }));
  }, [uiLang]);

  const captureHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();
    if (event.key === "Escape") { setHotkeyCapturing(false); event.currentTarget.blur(); return; }
    const shortcut = shortcutFromEvent(event);
    if (!shortcut) return;
    markHotkeyDirty("voice");
    setHotkey(shortcut); setHotkeyCapturing(false); event.currentTarget.blur();
  }, [markHotkeyDirty]);

  const captureTextTranslateHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();
    if (event.key === "Escape") { setTextHotkeyCapturing(false); event.currentTarget.blur(); return; }
    const shortcut = shortcutFromEvent(event);
    if (!shortcut) return;
    markHotkeyDirty("text");
    setTextTranslateHotkey(shortcut); setTextHotkeyCapturing(false); event.currentTarget.blur();
  }, [markHotkeyDirty]);

  const captureDesktopScreenHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();
    if (event.key === "Escape") { setDesktopScreenHotkeyCapturing(false); event.currentTarget.blur(); return; }
    const shortcut = shortcutFromEvent(event);
    if (!shortcut) return;
    markHotkeyDirty("screen");
    setDesktopScreenHotkey(shortcut); setDesktopScreenHotkeyCapturing(false); event.currentTarget.blur();
  }, [markHotkeyDirty]);

  const captureScreenReadHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();
    if (event.key === "Escape") { setScreenReadHotkeyCapturing(false); event.currentTarget.blur(); return; }
    const shortcut = shortcutFromEvent(event);
    if (!shortcut) return;
    markHotkeyDirty("read");
    setScreenReadHotkey(shortcut); setScreenReadHotkeyCapturing(false); event.currentTarget.blur();
  }, [markHotkeyDirty]);

  const captureDesktopExitHotkey = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault(); event.stopPropagation();

    const shortcut = shortcutFromEvent(event);
    if (!shortcut) return;
    markHotkeyDirty("screen");
    setDesktopExitHotkey(shortcut); setDesktopExitHotkeyCapturing(false); event.currentTarget.blur();
  }, [markHotkeyDirty]);

  const testScreenReadOutput = async (testVoice = false) => {
    setScreenReadTesting(true);
    setScreenReadTestIsVoice(testVoice);
    setScreenReadTestNotice(uiLang === "vi" ? (testVoice ? "Đang tạo và thử giọng…" : "Đang phát âm thử…") : (testVoice ? "Generating and testing voice…" : "Playing test sound…"));
    try {
      const response = await fetch(`${HTTP}/hotkey/test-output`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ output_device: screenReadOutputDevice, ...(testVoice ? {language:screenReadVoiceLanguage, voice:screenReadVoices[screenReadVoiceLanguage]} : {}) }) });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.detail || "Output test failed");
      setScreenReadTestNotice(`${uiLang === "vi" ? "Đã phát âm thử qua" : "Test sound played through"} ${payload.output_device}${payload.voice ? ` · ${payload.voice}` : ""}`);
    } catch (error) {
      setScreenReadTestNotice(error instanceof Error ? error.message : "Output test failed");
    } finally { setScreenReadTesting(false); }
  };

  const checkHelperStatus = useCallback(async () => {
    try {
      const response = await fetch(`${HTTP}/hotkey/status`);
      if (!response.ok) throw new Error("Helper status unavailable");
      const payload = await response.json();
      if (!payload.running) {
        setHelperNotice(uiLang === "vi" ? "Helper chưa chạy. Mở SpeakBridgeHotkey.exe hoặc khởi động SpeakBridge từ menu số 3." : "Helper is offline. Open SpeakBridgeHotkey.exe or start SpeakBridge from menu option 3.");
        return;
      }
      const bindings = Object.values(payload.hotkeys || {}) as { shortcut: string; active: boolean; error: string }[];
      setHelperNotice(bindings.map((binding) => `${binding.active ? "✓" : "⚠"} ${binding.shortcut}${binding.active ? "" : `: ${binding.error}`}`).join(" · "));
    } catch {
      setHelperNotice(uiLang === "vi" ? "Không kết nối được backend để kiểm tra helper." : "Could not reach the backend to check the helper.");
    }
  }, [uiLang]);

  useEffect(() => {
    if (!settingsOpen) return;
    const initial = setTimeout(() => void checkHelperStatus(), 0);
    const timer = setInterval(() => void checkHelperStatus(), 3000);
    return () => { clearTimeout(initial); clearInterval(timer); };
  }, [settingsOpen, checkHelperStatus]);

  const saveHotkeySettings = useCallback(async (section: "voice" | "text" | "read" | "screen" | "helper", override: Record<string, unknown> = {}) => {
    const version = (hotkeyNoticeVersions.current[section] || 0) + 1;
    hotkeyNoticeVersions.current[section] = version;
    const notice = (message: string) => { if (hotkeyNoticeVersions.current[section] === version) setHotkeyNotices((previous) => ({ ...previous, [section]: message })); };
    notice(uiLang === "vi" ? "Đang lưu…" : "Saving…");
    const allSettings: Record<string, unknown> = { hotkey, text_translate_hotkey: textTranslateHotkey, text_source_language: textSource, text_target_language: textTarget, microphone: hotkeyMicrophone, mode, source_language: hotkeySource, target_language: hotkeyTarget, translate: hotkeyTranslate, screen_hotkey: desktopScreenHotkey, screen_source_language: screenSource, screen_target_language: screenTarget, screen_processor: screenProcessor, screen_font_size: desktopScreenFontSize, screen_text_color: overlayForeground, screen_background_color: overlayBackground, screen_continuous: desktopScreenContinuous, screen_exit_hotkey: desktopExitHotkey, screen_refresh_seconds: desktopRefreshSeconds, screen_overlay_opacity: desktopOverlayOpacity, show_status_overlay: desktopStatusVisible, screen_read_hotkey: screenReadHotkey, screen_read_source_language: screenReadSource, screen_read_target_language: screenReadTarget, screen_read_mode: screenReadMode, screen_read_output_device: screenReadOutputDevice, screen_read_voices: screenReadVoices };
    const fields = {
      helper: ["show_status_overlay"],
      voice: ["hotkey", "microphone", "mode", "source_language", "target_language", "translate"],
      text: ["text_translate_hotkey", "text_source_language", "text_target_language"],
      read: ["screen_read_hotkey", "screen_read_source_language", "screen_read_target_language", "screen_read_mode", "screen_read_output_device", "screen_read_voices"],
      screen: ["screen_hotkey", "screen_source_language", "screen_target_language", "screen_processor", "screen_font_size", "screen_text_color", "screen_background_color", "screen_continuous", "screen_exit_hotkey", "screen_refresh_seconds", "screen_overlay_opacity", "show_status_overlay"],
    }[section];
    const changes = { ...Object.fromEntries(fields.map((field) => [field, allSettings[field]])), ...override };
    try {
      const response = await fetch(`${HTTP}/hotkey/settings`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
      const saved = await response.json();
      if (!response.ok) throw new Error(typeof saved.detail === "string" ? saved.detail : "Invalid settings");
      if (section === "read") setScreenReadHotkey(saved.screen_read_hotkey);
      const bindingKey = { voice: "hotkey", text: "text_translate_hotkey", read: "screen_read_hotkey", screen: "screen_hotkey", helper: "hotkey" }[section];
      notice(uiLang === "vi" ? "Đã lưu · đang chờ helper áp dụng…" : "Saved · waiting for helper…");
      for (let attempt = 0; attempt < 12; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        const runtime = await (await fetch(`${HTTP}/hotkey/status`)).json();
        if (runtime.running && fields.every((field) => JSON.stringify(runtime.settings?.[field]) === JSON.stringify(saved[field]))) {
          const binding = runtime.hotkeys?.[bindingKey];
          if (section !== "helper" && (!binding?.active || binding.shortcut !== saved[bindingKey])) throw new Error(binding?.error || "Windows did not register this shortcut");
          notice(`${uiLang === "vi" ? "✓ Đã áp dụng" : "✓ Applied"} · ${section === "helper" ? (saved.show_status_overlay ? "ON" : "OFF") : binding.shortcut}`);
          await checkHelperStatus();
          return;
        }
      }
      notice(uiLang === "vi" ? "Đã lưu, nhưng helper chưa xác nhận áp dụng. Kiểm tra helper hoặc thả phím đang giữ." : "Saved, but helper has not confirmed. Check helper or release held keys.");
    } catch (error) { notice(error instanceof Error ? error.message : "Hotkey error"); }
  }, [checkHelperStatus, overlayForeground, overlayBackground, desktopExitHotkey, desktopOverlayOpacity, desktopRefreshSeconds, desktopScreenContinuous, desktopScreenFontSize, desktopScreenHotkey, desktopStatusVisible, hotkey, hotkeyMicrophone, hotkeySource, hotkeyTarget, hotkeyTranslate, mode, screenProcessor, screenSource, screenTarget, screenReadHotkey, screenReadSource, screenReadTarget, screenReadMode, screenReadOutputDevice, screenReadVoices, textSource, textTarget, textTranslateHotkey, uiLang]);

  const openModelFolder = async (name: string) => {
    try {
      const response = await fetch(`${HTTP}/models/open-folder`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Could not open folder");
      setModelFolderNotice(`${uiLang === "vi" ? "Đã mở" : "Opened"}: ${payload.path}`);
    } catch (error) { setModelFolderNotice(error instanceof Error ? error.message : "Could not open folder"); }
  };

  const playSpeech = useCallback(async (url: string) => {
    if (!speechPlayerRef.current) speechPlayerRef.current = new SpeechPlayer((source) => new Audio(source), (speechAudio, source) => {
      const audio = speechAudio as HTMLAudioElement;
      let cancelled = false; let timer: number | undefined; let decoder: AudioContext | undefined;
      // Meter work must never delay playback or hold the queue when decode hangs.
      void (async () => {
        try {
          decoder = new AudioContext();
          const decoded = await decoder.decodeAudioData(await (await fetch(source)).arrayBuffer());
          if (cancelled) return;
          const pcm = decoded.getChannelData(0);
          timer = window.setInterval(() => {
            const start = Math.floor(audio.currentTime * decoded.sampleRate);
            const end = Math.min(pcm.length, start + Math.round(decoded.sampleRate * 0.05));
            let sum = 0; for (let i = start; i < end; i++) sum += pcm[i] * pcm[i];
            setTtsLevel(audio.paused ? 0 : Math.min(1, Math.sqrt(sum / Math.max(1, end - start)) * 6 * audio.volume));
          }, 70);
        } catch { /* A meter failure does not cancel speech. */ }
      })();
      return () => { cancelled = true; if (timer !== undefined) window.clearInterval(timer); void decoder?.close().catch(() => {}); setTtsLevel(0); };
    });
    try { await speechPlayerRef.current.enqueue(url, outputId); }
    catch (error) { if (error instanceof Error && error.name !== "AbortError") setOutNotice(error.message); throw error; }
  }, [outputId]);

  const testSelectedVoice = async () => {
    setVoiceTesting(true); setOutNotice(uiLang === "vi" ? "Đang tạo giọng thử…" : "Generating voice sample…");
    try {
      const response = await fetch(`${HTTP}/tts/test`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({language:outTarget, voice})});
      const payload = await response.json();
      if (!response.ok || !payload.audio_base64) throw new Error(payload.detail || "Speech test failed");
      await playSpeech(`data:audio/wav;base64,${payload.audio_base64}`);
      setOutNotice(uiLang === "vi" ? `✓ Đã phát giọng ${payload.voice}. Nếu chọn CABLE Input, tiếng đi vào mic ảo, không phát ở tai nghe.` : `✓ Played ${payload.voice}. CABLE Input routes to the virtual microphone, not your headphones.`);
    } catch (error) { setOutNotice(error instanceof Error ? error.message : "Speech test failed"); }
    finally { setVoiceTesting(false); }
  };

  useEffect(() => {
    void fetch(`${HTTP}/tts/voices`).then((response) => response.json()).then((payload) => { if (payload.ok) setVoiceOptions(payload.languages || {}); }).catch(() => {});
    return () => speechPlayerRef.current?.stop();
  }, []);

  const saveAdvisorConfig = useCallback(async () => {
    setAdvisorStatus(uiLang === "vi" ? "Đang lưu cấu hình…" : "Saving settings…");
    try {
      const response = await fetch(`${HTTP}/advisor/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: advisorEnabled, provider: advisorProvider, base_url: advisorBaseUrl, model: advisorModel, api_key: advisorApiKey, strict_scope: advisorStrict, deal_mode: advisorDeal, trigger_mode: advisorTrigger, silence_seconds: advisorDelay, max_suggestions: 3, knowledge_context: advisorKnowledgeContext }) });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Advisor settings error");
      setAdvisorHasKey(Boolean(payload.has_api_key)); setAdvisorApiKey(""); setAdvisorStatus(uiLang === "vi" ? "Đã lưu cấu hình trợ lý" : "Advisor settings saved"); return true;
    } catch (error) { setAdvisorStatus(error instanceof Error ? error.message : "Advisor settings error"); return false; }
  }, [advisorApiKey, advisorBaseUrl, advisorDeal, advisorDelay, advisorEnabled, advisorKnowledgeContext, advisorModel, advisorProvider, advisorStrict, advisorTrigger, uiLang]);

  const testAdvisorApi = useCallback(async () => {
    setAdvisorStatus(uiLang === "vi" ? "Đang kiểm tra API…" : "Testing API…");
    try { if (!await saveAdvisorConfig()) return; setAdvisorStatus(uiLang === "vi" ? "Đang gửi yêu cầu thử tới API…" : "Sending a test request…"); const response = await fetch(`${HTTP}/advisor/test`, { method: "POST" }); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "API test failed"); setAdvisorStatus(`✓ API ${advisorProvider} · ${advisorModel} · ${payload.latency_ms} ms · ${payload.reply}`); }
    catch (error) { setAdvisorStatus(error instanceof Error ? error.message : "API test failed"); }
  }, [advisorModel, advisorProvider, saveAdvisorConfig, uiLang]);

  const uploadAdvisorDocument = useCallback(async (file: File) => {
    setAdvisorStatus(uiLang === "vi" ? `Đang đọc ${file.name}…` : `Reading ${file.name}…`);
    try {
      if (file.size > 12_000_000) throw new Error(uiLang === "vi" ? "File vượt quá 12 MB" : "File exceeds 12 MB");
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ""; for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
      const response = await fetch(`${HTTP}/advisor/documents`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, content_base64: btoa(binary), category: advisorDocCategory }) });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Document upload failed"); await loadAdvisor(); setAdvisorStatus(uiLang === "vi" ? `Đã thêm ${file.name}` : `Added ${file.name}`);
    } catch (error) { setAdvisorStatus(error instanceof Error ? error.message : "Document upload failed"); }
  }, [advisorDocCategory, loadAdvisor, uiLang]);

  const deleteAdvisorDocument = useCallback(async (id: string) => {
    try { const response = await fetch(`${HTTP}/advisor/documents/${id}`, { method: "DELETE" }); if (!response.ok) throw new Error(); setAdvisorDocs((items) => items.filter((item) => item.id !== id)); }
    catch { setAdvisorStatus(uiLang === "vi" ? "Không xóa được tài liệu" : "Could not delete document"); }
  }, [uiLang]);

  const generateAdvisorSuggestions = useCallback(async (customerOriginal: string, customerTranslation: string) => {
    if (!advisorEnabled) return;
    const generation = ++advisorGenerationRef.current; setAdvisorLoading(true); setAdvisorStatus(t.advisorThinking);
    const incomingHistory = [...inFeedRef.current].reverse().filter((item) => item.state === "done").slice(-8).map((item) => ({ speaker: "customer", text: item.translation || item.source }));
    const outgoingHistory = [...outFeedRef.current].reverse().filter((item) => item.state === "done").slice(-8).map((item) => ({ speaker: "me", text: item.source }));
    try {
      const response = await fetch(`${HTTP}/advisor/suggest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ customer_text: customerTranslation || customerOriginal, customer_original: customerOriginal, history: [...incomingHistory, ...outgoingHistory].slice(-16), meeting_context: meetingContext, knowledge_context: advisorKnowledgeContext }) });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Advisor failed"); if (generation !== advisorGenerationRef.current) return;
      setAdvisorSuggestions(payload.suggestions || []); setAdvisorFollowUp(payload.follow_up_question || ""); setAdvisorStatus(payload.notice || `${payload.provider || advisorProvider} · ${payload.model || advisorModel}`);
    } catch (error) { if (generation === advisorGenerationRef.current) { setAdvisorSuggestions([]); setAdvisorFollowUp(""); setAdvisorStatus(error instanceof Error ? error.message : "Advisor failed"); } }
    finally { if (generation === advisorGenerationRef.current) setAdvisorLoading(false); }
  }, [advisorEnabled, advisorKnowledgeContext, advisorModel, advisorProvider, meetingContext, t.advisorThinking]);

  const scheduleAdvisor = useCallback((customerOriginal: string, customerTranslation: string) => {
    if (!advisorEnabled) return; if (advisorTimerRef.current !== null) window.clearTimeout(advisorTimerRef.current);
    setAdvisorStatus(advisorTrigger === "sentence" ? (uiLang === "vi" ? "Đã nhận đủ câu · chuẩn bị gợi ý" : "Sentence complete · preparing suggestions") : (uiLang === "vi" ? `Chờ ${advisorDelay}s im lặng…` : `Waiting for ${advisorDelay}s silence…`));
    advisorTimerRef.current = window.setTimeout(() => void generateAdvisorSuggestions(customerOriginal, customerTranslation), advisorTrigger === "sentence" ? 150 : advisorDelay * 1000);
  }, [advisorDelay, advisorEnabled, advisorTrigger, generateAdvisorSuggestions, uiLang]);

  const stopOutgoing = useCallback(() => {
    speechPlayerRef.current?.stop(); setTtsLevel(0);
    if (micWatchdogRef.current !== null) window.clearTimeout(micWatchdogRef.current); micWatchdogRef.current = null; sentFramesRef.current = 0;
    processorRef.current?.disconnect(); processorRef.current = null; void contextRef.current?.close(); contextRef.current = null; streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null; outWs.current?.close(); outWs.current = null;
    setOutPreparing(false); setOutRunning(false); setOutListening(false); setLevel(0); setOutNotice(COPY[uiLang].stoppedMic);
  }, [uiLang]);

  const startOutgoing = useCallback(async () => {
    if (!online) return setOutNotice(COPY[uiLang].offline);
    try {
      setOutPreparing(true); setOutNotice(mode === "quality" ? (uiLang === "vi" ? "Đang nạp Whisper large-v3…" : "Loading Whisper large-v3…") : (uiLang === "vi" ? "Đang nạp Whisper Turbo…" : "Loading Whisper Turbo…")); const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext; const context = new AudioContextClass(); contextRef.current = context; await context.resume();
      const [prepareResponse, stream] = await Promise.all([fetch(`${HTTP}/prepare/${mode}`, { method: "POST" }), navigator.mediaDevices.getUserMedia({ audio: { deviceId: micId === "default" ? undefined : { exact: micId }, channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })]);
      if (!prepareResponse.ok) { stream.getTracks().forEach((track) => track.stop()); const details = await prepareResponse.json().catch(() => ({})); throw new Error(details.detail || "Model preparation failed"); } streamRef.current = stream; await refreshDevices();
      const socket = new WebSocket(OUT_WS); socket.binaryType = "arraybuffer"; outWs.current = socket;
      socket.onopen = () => { sentFramesRef.current = 0; socket.send(JSON.stringify({ type: "config", mode, voice: outTarget === "zh" ? "zm_yunxi" : voice, glossary: glossaryItems(), meeting_context: meetingContext, source_language: outSource, target_language: outTarget, speak_translation: speakTranslation && ttsSupported })); setOutPreparing(false); setOutRunning(true); setOutNotice(uiLang === "vi" ? "Hãy nói một câu · thanh mức mic phải chuyển động" : "Speak a sentence · the microphone meter should move"); micWatchdogRef.current = window.setTimeout(() => { if (sentFramesRef.current === 0) setOutNotice(uiLang === "vi" ? "Không nhận được âm thanh; hãy chọn lại microphone." : "No audio received; select the correct microphone."); }, 4000); };
      socket.onmessage = (event) => { const message = JSON.parse(event.data); if (message.type === "vad") setOutListening(message.active); if (message.type === "processing") setOutFeed((items) => [{ id: message.id, source: t.recognizing, translation: "", sourceLang: outSource, targetLang: outTarget, createdAt: Date.now(), state: "processing" as State }, ...items].slice(0, 100)); if (message.type === "result") { setOutFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: message.source, translation: message.translation, sourceLang: message.source_lang || outSource, targetLang: message.target_lang || outTarget, latencyMs: message.latency_ms, state: "done" } : item)); if (message.audio_base64) { void playSpeech(`data:audio/wav;base64,${message.audio_base64}`).catch(() => {}); } } if (message.type === "error") { setOutNotice(message.message || "Pipeline error"); if (message.id) setOutFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: uiLang === "vi" ? "Đoạn âm thanh đã được bỏ" : "Audio segment discarded", translation: message.message || "Low confidence", state: "error" } : item)); } if (message.type === "status") setOutNotice(message.message); };
      socket.onclose = () => { setOutPreparing(false); setOutRunning(false); setOutListening(false); }; if (context.state !== "running") await context.resume(); const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1); processorRef.current = processor;
      processor.onaudioprocess = (event) => { const samples = event.inputBuffer.getChannelData(0); let sum = 0; for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i]; setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 6)); if (socket.readyState === WebSocket.OPEN) { socket.send(floatToPcm16(resampleTo16k(samples, context.sampleRate)).buffer); sentFramesRef.current += 1; } };
      const gain = context.createGain(); gain.gain.value = 0; source.connect(processor); processor.connect(gain); gain.connect(context.destination);
    } catch (error) { stopOutgoing(); setOutNotice(error instanceof Error ? error.message : "Microphone error"); }
  }, [glossaryItems, meetingContext, micId, mode, online, outSource, outTarget, playSpeech, refreshDevices, speakTranslation, stopOutgoing, t, ttsSupported, uiLang, voice]);

  const stopIncoming = useCallback(() => { inWs.current?.close(); inWs.current = null; setInPreparing(false); setInRunning(false); setInListening(false); setInLevel(0); setInNotice(COPY[uiLang].stoppedOther); }, [uiLang]);
  const startIncoming = useCallback(async () => {
    if (!online) return setInNotice(COPY[uiLang].offline);
    try { setInPreparing(true); setInNotice(mode === "quality" ? (uiLang === "vi" ? "Đang nạp Whisper large-v3…" : "Loading Whisper large-v3…") : (uiLang === "vi" ? "Đang nạp Whisper Turbo…" : "Loading Whisper Turbo…")); const prepareResponse = await fetch(`${HTTP}/prepare/${mode}`, { method: "POST" }); if (!prepareResponse.ok) { const details = await prepareResponse.json().catch(() => ({})); throw new Error(details.detail || "Model preparation failed"); } const socket = new WebSocket(IN_WS); inWs.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: "config", mode, device: speakerDevice, glossary: glossaryItems(), meeting_context: meetingContext, source_language: inSource, target_language: inTarget }));
      socket.onmessage = (event) => { const message = JSON.parse(event.data); if (message.type === "level") setInLevel(Math.min(1, Math.max(0, Number(message.rms) * 6 || 0))); if (message.type === "vad") setInListening(message.active); if (message.type === "status") { setInPreparing(false); setInRunning(true); setInNotice(message.message); } if (message.type === "processing") setInFeed((items) => [{ id: message.id, source: t.recognizing, translation: "", sourceLang: inSource, targetLang: inTarget, createdAt: Date.now(), state: "processing" as State }, ...items].slice(0, 100)); if (message.type === "result") { setInFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: message.source, translation: message.translation, sourceLang: message.source_lang || inSource, targetLang: inTarget, latencyMs: message.latency_ms, state: "done" } : item)); scheduleAdvisor(message.source || "", message.translation || message.source || ""); } if (message.type === "error") { setInPreparing(false); setInNotice(message.message || "Pipeline error"); if (message.id) setInFeed((items) => items.map((item) => item.id === message.id ? { ...item, source: uiLang === "vi" ? "Đoạn âm thanh đã được bỏ" : "Audio segment discarded", translation: message.message || "Low confidence", state: "error" } : item)); } };
      socket.onclose = () => { setInPreparing(false); setInRunning(false); setInListening(false); setInLevel(0); };
    } catch (error) { stopIncoming(); setInNotice(error instanceof Error ? error.message : "System audio error"); }
  }, [glossaryItems, inSource, inTarget, meetingContext, mode, online, scheduleAdvisor, speakerDevice, stopIncoming, t, uiLang]);

  const stopScreen = useCallback(() => {
    if (screenLoopRef.current !== null) window.clearInterval(screenLoopRef.current); screenLoopRef.current = null;
    screenStreamRef.current?.getTracks().forEach((track) => track.stop()); screenStreamRef.current = null;
    if (screenVideoRef.current) screenVideoRef.current.srcObject = null;
    if (screenThumbVideoRef.current) screenThumbVideoRef.current.srcObject = null;
    if (document.fullscreenElement === screenStageRef.current) void document.exitFullscreen();
    screenGenerationRef.current += 1; setDraftRegion(null); draftRegionRef.current = null; screenLastFrameRef.current = ""; screenLastFrameAtRef.current = 0; screenDragRef.current = null; screenEmptyFramesRef.current = 0;
    screenBusyStartedRef.current = null; setScreenScanElapsed(null); setScreenLastLatency(null);
    setScreenPreparing(false); setScreenRunning(false); setScreenRegion(null); setScreenOverlays([]); setScreenNotice(uiLang === "vi" ? "Đã dừng dịch màn hình" : "Screen translation stopped");
  }, [uiLang]);

  const captureScreenFrame = useCallback(async () => {
    const video = screenVideoRef.current; const canvas = screenCanvasRef.current;
    if (!video || !canvas || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || screenBusyRef.current) return;
    const sourceWidth = video.videoWidth; const sourceHeight = video.videoHeight;
    if (!sourceWidth || !sourceHeight) return;
    if (screenCaptureMode === "region" && !screenRegion) { setScreenNotice(t.screenSelecting); return; }
    screenBusyRef.current = true;
    const generation = screenGenerationRef.current;
    try {
      const region = screenCaptureMode === "full" ? { x: 0, y: 0, width: 1, height: 1 } : screenRegion!;
      const sx = Math.max(0, Math.round(region.x * sourceWidth)); const sy = Math.max(0, Math.round(region.y * sourceHeight));
      const sw = Math.max(2, Math.min(sourceWidth - sx, Math.round(region.width * sourceWidth))); const sh = Math.max(2, Math.min(sourceHeight - sy, Math.round(region.height * sourceHeight)));
      const scale = Math.min(1, 1600 / sw, 1000 / sh); canvas.width = Math.max(2, Math.round(sw * scale)); canvas.height = Math.max(2, Math.round(sh * scale));
      const context = canvas.getContext("2d", { alpha: false }); if (!context) return;
      context.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

      const sample = document.createElement("canvas"); sample.width = 96; sample.height = 54; const sampleContext = sample.getContext("2d", { willReadFrequently: true });
      if (sampleContext) {
        sampleContext.drawImage(canvas, 0, 0, sample.width, sample.height); const pixels = sampleContext.getImageData(0, 0, sample.width, sample.height).data; let hash = 2166136261;
        for (let index = 0; index < pixels.length; index += 4) { hash ^= ((pixels[index] + pixels[index + 1] + pixels[index + 2]) / 24) | 0; hash = Math.imul(hash, 16777619); }
        const signature = String(hash >>> 0);
        if (signature === screenLastFrameRef.current && Date.now() - screenLastFrameAtRef.current < 5000) return;
        screenLastFrameRef.current = signature; screenLastFrameAtRef.current = Date.now();
      }

      const encoded = canvas.toDataURL("image/jpeg", 0.84).split(",", 2)[1];
      const scanStarted = performance.now(); screenBusyStartedRef.current = scanStarted; setScreenScanElapsed(0);
      const response = await fetch(`${HTTP}/ocr/translate`, { method: "POST", headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(30000), body: JSON.stringify({ image_base64: encoded, source_language: screenSource, target_language: screenTarget, processor: screenProcessor, mode, previous_text: screenLastTextRef.current }) });
      const payload = await response.json(); if (generation !== screenGenerationRef.current) return; if (!response.ok) throw new Error(payload.detail || "OCR failed");
      setScreenLastLatency(Math.round(performance.now() - scanStarted));
      setScreenActualProcessor(payload.processor || screenProcessor);
      if (payload.unchanged) {
        setScreenNotice(uiLang === "vi" ? "Chữ chưa thay đổi; giữ bản dịch hiện tại" : "Text unchanged; keeping the current translation");
        return;
      }
      if (payload.warning) setScreenNotice(payload.warning);
      else if (!payload.source) { setScreenNotice(t.screenNoText); screenEmptyFramesRef.current += 1; if (screenEmptyFramesRef.current >= 3) setScreenOverlays([]); }
      else if (!payload.translation) { screenLastFrameRef.current = ""; screenLastFrameAtRef.current = 0; setScreenNotice(uiLang === "vi" ? "Đã thấy chữ nhưng chưa dịch được; sẽ thử lại" : "Text detected but not translated; retrying"); }
      else setScreenNotice(`${t.screenWatching} · ${(payload.latency_ms / 1000).toFixed(1)}s · ${(payload.processor || screenProcessor).toUpperCase()}`);
      if (payload.source && !payload.unchanged && payload.translation) {
        screenEmptyFramesRef.current = 0;
        screenLastTextRef.current = payload.source;
        const overlays = (payload.regions || []).filter((item: ScreenOverlay) => item.translation).map((item: ScreenOverlay) => ({ ...item, x: region.x + item.x * region.width, y: region.y + item.y * region.height, width: item.width * region.width, height: item.height * region.height }));
        setScreenOverlays(overlays);
        setScreenFeed((items) => [{ id: `${Date.now()}`, source: payload.source, translation: payload.translation, sourceLang: screenSource, targetLang: screenTarget, latencyMs: payload.latency_ms, createdAt: Date.now(), state: "done" as State }, ...items].slice(0, 100));
      }
    } catch (error) { if (generation === screenGenerationRef.current) { screenLastFrameRef.current = ""; screenLastFrameAtRef.current = 0; setScreenNotice(error instanceof Error ? error.message : "Screen OCR error"); } }
    finally { screenBusyRef.current = false; if (generation === screenGenerationRef.current) { screenBusyStartedRef.current = null; setScreenScanElapsed(null); } }
  }, [mode, screenCaptureMode, screenProcessor, screenRegion, screenSource, screenTarget, t.screenNoText, t.screenSelecting, t.screenWatching, uiLang]);

  const startScreen = useCallback(async () => {
    if (!online) return setScreenNotice(COPY[uiLang].offline);
    try {
      setScreenPreparing(true); setScreenNotice(uiLang === "vi" ? "Trong hộp thoại Chrome, chọn một tab hoặc cửa sổ rồi bấm Chia sẻ…" : "In the Chrome picker, select a tab or window and click Share…");
      const media = await requestScreenStream(); screenStreamRef.current = media;
      const track = media.getVideoTracks()[0]; track.addEventListener("ended", stopScreen, { once: true });
      if (!screenVideoRef.current) throw new Error("Screen preview is unavailable"); screenVideoRef.current.srcObject = media; await screenVideoRef.current.play();
      if (screenVideoRef.current.videoWidth && screenVideoRef.current.videoHeight) setScreenAspectRatio(screenVideoRef.current.videoWidth / screenVideoRef.current.videoHeight);
      const prepareResponse = await fetch(`${HTTP}/ocr/prepare/${screenProcessor}?language=${encodeURIComponent(screenSource)}`, { method: "POST" }); const prepared = await prepareResponse.json(); if (!prepareResponse.ok) throw new Error(prepared.detail || "OCR preparation failed");
      setScreenActualProcessor(prepared.processor || screenProcessor); setScreenPreparing(false); setScreenRunning(true); setScreenNotice(prepared.warning || (screenCaptureMode === "region" ? COPY[uiLang].screenSelecting : COPY[uiLang].screenWatching));
      screenLastFrameRef.current = ""; screenLastFrameAtRef.current = 0; screenLastTextRef.current = ""; screenEmptyFramesRef.current = 0; setScreenLastLatency(null); setScreenOverlays([]);
    } catch (error) { stopScreen(); setScreenNotice(error instanceof Error ? error.message : "Screen capture error"); }
  }, [online, screenCaptureMode, screenProcessor, screenSource, stopScreen, uiLang]);

  const screenPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !screenRunning || screenCaptureMode !== "region" || screenRegion || !screenSurfaceRef.current) return; const bounds = screenSurfaceRef.current.getBoundingClientRect(); const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)); const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
    event.preventDefault(); screenDragRef.current = { x, y }; event.currentTarget.setPointerCapture(event.pointerId);
    draftRegionRef.current = { x, y, width: 0, height: 0 }; setDraftRegion(draftRegionRef.current);
  }, [screenCaptureMode, screenRegion, screenRunning]);

  const screenPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!screenDragRef.current || !screenSurfaceRef.current) return; const bounds = screenSurfaceRef.current.getBoundingClientRect(); const currentX = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)); const currentY = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)); const start = screenDragRef.current;
    draftRegionRef.current = { x: Math.min(start.x, currentX), y: Math.min(start.y, currentY), width: Math.abs(currentX - start.x), height: Math.abs(currentY - start.y) };
    setDraftRegion(draftRegionRef.current);
  }, []);

  const screenPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!screenDragRef.current) return;
    const region = draftRegionRef.current;
    screenDragRef.current = null; draftRegionRef.current = null; setDraftRegion(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (event.type === "pointercancel") return;
    screenGenerationRef.current += 1;
    setScreenRegion(region && region.width > 0.01 && region.height > 0.01 ? region : null);
    setScreenOverlays([]); screenLastFrameRef.current = ""; screenLastTextRef.current = "";
  }, []);

  useEffect(() => {
    if (!screenRunning) return;
    if (screenLoopRef.current !== null) window.clearInterval(screenLoopRef.current);
    const firstFrame = window.setTimeout(() => void captureScreenFrame(), 0);
    screenLoopRef.current = window.setInterval(() => void captureScreenFrame(), Math.round(desktopRefreshSeconds * 1000));
    return () => { window.clearTimeout(firstFrame); if (screenLoopRef.current !== null) window.clearInterval(screenLoopRef.current); screenLoopRef.current = null; };
  }, [captureScreenFrame, desktopRefreshSeconds, screenRunning]);

  useEffect(() => {
    if (!screenRunning) return;
    const timer = window.setInterval(() => { if (screenBusyStartedRef.current !== null) setScreenScanElapsed((performance.now() - screenBusyStartedRef.current) / 1000); }, 100);
    return () => window.clearInterval(timer);
  }, [screenRunning]);

  useEffect(() => {
    const thumbnail = screenThumbVideoRef.current;
    const stream = screenStreamRef.current;
    if (!screenRunning || !thumbnail || !stream) return;
    thumbnail.srcObject = stream;
    void thumbnail.play().catch(() => undefined);
    return () => { thumbnail.srcObject = null; };
  }, [screenPanelOpen, screenRegion, screenRunning]);

  useEffect(() => () => { screenStreamRef.current?.getTracks().forEach((track) => track.stop()); }, []);

  const beginDashboardResize = useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (!dashboardRef.current) return;
    event.preventDefault();
    const resize = (pointerEvent: PointerEvent) => {
      const bounds = dashboardRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const width = ((bounds.right - pointerEvent.clientX) / bounds.width) * 100;
      setScreenPanelWidth(Math.max(30, Math.min(58, width)));
    };
    const finish = () => { window.removeEventListener("pointermove", resize); window.removeEventListener("pointerup", finish); };
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", finish, { once: true });
  }, []);

  const exportDoc = (items: FeedItem[], title: string) => {
    const rows = [...items].reverse().filter((item) => item.state === "done").map((item) => `<tr><td><b>${escapeHtml(item.sourceLang.toUpperCase())}</b><br>${escapeHtml(item.source)}</td><td><b>${escapeHtml(item.targetLang.toUpperCase())}</b><br>${escapeHtml(item.translation)}</td></tr>`).join("");
    const html = `<html><head><meta charset="utf-8"><style>body{font-family:Arial}table{border-collapse:collapse;width:100%}td{border:1px solid #bbb;padding:10px;vertical-align:top}</style></head><body><h1>${escapeHtml(title)}</h1><p>${new Date().toLocaleString()}</p><table>${rows}</table></body></html>`;
    const url = URL.createObjectURL(new Blob([html], { type: "application/msword;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `SpeakBridge-${title.replace(/\W+/g, "-")}-${new Date().toISOString().slice(0, 10)}.doc`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const anyRunning = outRunning || inRunning || outPreparing || inPreparing;
  const transcriptBoard = (kind: "incoming" | "outgoing", items: FeedItem[], sourceCode: string, targetCode: string, listening: boolean) => {
    const incoming = kind === "incoming"; const number = incoming ? "02A" : "02B"; const running = incoming ? inRunning : outRunning; const notice = incoming ? inNotice : outNotice;
    const title = incoming ? (uiLang === "vi" ? "Bên kia nói" : "Remote side") : (uiLang === "vi" ? "Tôi nói" : "My voice");
    return <section className={`streamCard ${incoming ? "incomingCard" : "outgoingCard"} ${listening ? "live" : ""}`}>
      <header className="streamCardHeader">
        <div className="streamIdentity"><div className={`streamSignal ${listening ? "active" : ""}`}><span className="streamIcon" aria-hidden="true">{incoming ? "🔊" : "🎙"}</span><AudioMeter value={incoming ? inLevel : level} label={incoming ? "System audio input" : "Microphone input"} /></div><div><small>{number}</small><h2>{title}</h2></div></div>
        <div className="streamHeaderActions"><button onClick={() => exportDoc(items, number)} disabled={!items.some((item) => item.state === "done")}>{t.export}</button><button onClick={() => incoming ? setInFeed([]) : setOutFeed([])} disabled={!items.length}>↻ {t.clear}</button></div>
      </header>
      <div className="streamControls">
        <div className="compactLanguagePair"><LanguageSelect value={sourceCode} onChange={incoming ? setInSource : setOutSource} allowAuto disabled={running} /><b>→</b><LanguageSelect value={targetCode} onChange={incoming ? setInTarget : (value) => { setOutTarget(value); setVoice(value === "zh" ? "zm_yunxi" : ["vi", "ja", "ko"].includes(value) ? "M1" : "am_adam"); }} disabled={running} /></div>
        {incoming ? <>
          <label className="compactControl playbackControl"><span aria-hidden="true">◖</span><select aria-label={t.playbackDevice} title={t.playbackHelp} value={speakerDevice} onChange={(event) => setSpeakerDevice(event.target.value)} disabled={inRunning}><option value="__default__">{t.defaultPlayback}</option>{speakerDevices.map((device) => <option key={device} value={device}>{device}</option>)}</select></label>
          <button className={`compactStart incomingStart ${inRunning ? "stop" : ""}`} onClick={inRunning ? stopIncoming : startIncoming} disabled={inPreparing}>{inRunning ? "■" : inPreparing ? "◌" : "▶"}<span>{inRunning ? t.stopOther : inPreparing ? t.preparing : t.startOther}</span></button>
        </> : <>
          <label className="compactControl"><span aria-hidden="true">●</span><select aria-label={t.microphone} value={micId} onChange={(event) => setMicId(event.target.value)} disabled={outRunning}><option value="default">{t.defaultMic}</option>{micDevices.filter((device) => device.deviceId !== "default").map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</select></label>
          <label className="compactControl"><span aria-hidden="true">◖</span><select aria-label={t.ttsOutput} value={outputId} onChange={(event) => setOutputId(event.target.value)} disabled={outRunning}><option value="default">{t.defaultSpeaker}</option>{outputDevices.filter((device) => device.deviceId !== "default").map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}</select></label>
          {ttsSupported && <select className="voiceSelect" aria-label={t.voice} value={voice} onChange={(event) => { speechPlayerRef.current?.stop(); setVoice(event.target.value); setOutNotice(uiLang === "vi" ? "Đã đổi giọng · bấm Thử giọng hoặc bắt đầu nói." : "Voice changed · test the voice or start speaking."); }} disabled={outRunning || outPreparing || voiceTesting}>{(voiceOptions[outTarget] || []).map((option) => <option key={option.id} value={option.id} disabled={!option.installed}>{option.label}{option.installed ? "" : (uiLang === "vi" ? " · thiếu tệp" : " · missing files")}</option>)}</select>}
          {ttsSupported && <button className="voiceTestButton" disabled={outRunning || outPreparing || voiceTesting || !voiceOptions[outTarget]?.some((option) => option.id === voice && option.installed)} onClick={() => void testSelectedVoice()}>{voiceTesting ? "◌" : "▶"} {uiLang === "vi" ? "Thử giọng" : "Test voice"}</button>}
          <label className="compactToggle"><input type="checkbox" checked={speakTranslation && ttsSupported} onChange={(event) => setSpeakTranslation(event.target.checked)} disabled={!ttsSupported || outRunning} /><span>TTS</span></label>
          {!ttsSupported && <small title={t.textOnly}>{uiLang === "vi" ? "Chỉ phụ đề · thiếu TTS" : "Subtitles only · TTS missing"}</small>}
          <button className={`compactStart outgoingStart ${outRunning ? "stop" : ""}`} onClick={outRunning ? stopOutgoing : startOutgoing} disabled={outPreparing || voiceTesting}>{outRunning ? "■" : outPreparing ? "◌" : "●"}<span>{outRunning ? t.stopMic : outPreparing ? t.preparing : t.startMe}</span></button>
        </>}
      </div>
      {incoming ? (inPreparing || inRunning || (notice !== t.readyOther && notice !== t.stoppedOther)) && <div className="streamStatus"><span className={running ? "statusOnline" : ""}>{notice}</span></div> : <div className="streamStatus"><span className={running ? "statusOnline" : ""}>{notice}</span><span className="audioMeterLabel">IN</span><AudioMeter value={level} label="Microphone level" /><span className="audioMeterLabel">TTS OUT</span><AudioMeter value={ttsLevel} label="Translated speech output" /></div>}
      {!incoming && <details className="routingHelp"><summary>{cableInstalled === true ? "✓ VB-CABLE" : cableInstalled === false ? "⚠ VB-CABLE chưa được phát hiện" : "VB-CABLE · chưa kiểm tra"} · {uiLang === "vi" ? "Để bên kia nghe: chọn đầu ra CABLE Input" : "Route speech to CABLE Input"}</summary><p>{t.routeOk}</p><p>{t.routeWarn}</p><p>{uiLang === "vi" ? "Chỉ cần driver khi truyền giọng dịch vào cuộc gọi. Nếu chưa cài: tải VB-CABLE tại trang chính thức, giải nén, chạy VBCABLE_Setup_x64.exe bằng quyền Administrator, chọn Install Driver, rồi khởi động lại Windows. Không bật Listen to this device." : "For calls, install VB-CABLE from the official site: unzip, run VBCABLE_Setup_x64.exe as Administrator, Install Driver, then restart Windows. Keep Listen to this device disabled."}</p><a href="https://vb-audio.com/Cable/" target="_blank" rel="noreferrer">{uiLang === "vi" ? "Tải / hướng dẫn VB-CABLE" : "Get VB-CABLE"}</a><button onClick={() => void refreshDevices()}>{uiLang === "vi" ? "Kiểm tra lại thiết bị" : "Refresh devices"}</button></details>}
      <div className="compactFeed">{items.length === 0 ? <div className="compactEmpty"><span>⌁</span><p>{incoming ? t.emptyOther : t.emptyMe}</p></div> : items.map((item) => <article key={item.id} className={`compactFeedItem ${item.state}`}><time>{feedTime(item)}</time><i className="turnBar" /><div className="turnCopy"><p>{item.source}</p><p>{item.translation || (item.state === "processing" ? t.translating : "—")}</p></div><div className="turnMeta">{item.state === "processing" ? <span>{t.recognizing}</span> : item.latencyMs !== undefined ? <small>{(item.latencyMs / 1000).toFixed(1)}s</small> : null}</div></article>)}</div>
    </section>;
  };

  const advisorBoard = <section className={`advisorBoard ${advisorEnabled ? "enabled" : ""}`}><div className="panelHeader"><div className="sectionTitle"><span>AI</span><h2>{t.advisorTitle}</h2></div><label className="miniToggle"><input type="checkbox" checked={advisorEnabled} onChange={(event) => setAdvisorEnabled(event.target.checked)} /><span>{advisorEnabled ? "ON" : "OFF"}</span></label></div>
    <details className="advisorConfig"><summary><span>{uiLang === "vi" ? "Cấu hình & tài liệu trợ lý" : "Advisor settings & documents"}</span><span className="advisorInputStatus"><i className={advisorHasKey ? "ready" : "missing"}>{advisorHasKey ? "✓" : "!"} API</i><i className={advisorKnowledgeContext.trim() ? "ready" : "missing"}>{advisorKnowledgeContext.trim() ? "✓" : "!"} Context</i><i className={advisorDocs.length ? "ready" : "missing"}>{advisorDocs.length ? "✓" : "!"} {advisorDocs.length} file</i><i className={inFeed.some((item) => item.state === "done") ? "ready" : "waiting"}>↻ {inFeed.filter((item) => item.state === "done").length} log</i></span></summary>
      <div className="advisorQuickSettings"><label className="checkField"><input type="checkbox" checked={advisorStrict} onChange={(event) => setAdvisorStrict(event.target.checked)} /><span>{t.strictScope}</span></label><label className="checkField"><input type="checkbox" checked={advisorDeal} onChange={(event) => setAdvisorDeal(event.target.checked)} /><span>{t.dealMode}</span></label>
        <label className="field"><span>{t.silenceDelay}</span><select value={advisorTrigger} onChange={(event) => setAdvisorTrigger(event.target.value as "silence" | "sentence")}><option value="silence">{uiLang === "vi" ? "Sau khi im lặng" : "After silence"}</option><option value="sentence">{uiLang === "vi" ? "Sau mỗi câu hoàn chỉnh" : "After every complete sentence"}</option></select></label>{advisorTrigger === "silence" && <label className="compactNumber"><input type="number" min="0.5" max="20" step="0.5" value={advisorDelay} onChange={(event) => setAdvisorDelay(Math.max(.5, Math.min(20, Number(event.target.value) || 3)))} /><span>{uiLang === "vi" ? "giây" : "seconds"}</span></label>}
        <label className="advisorContextField"><span>{uiLang === "vi" ? "Context tư vấn / hồ sơ dịch vụ" : "Advisor context / service profile"}</span><textarea value={advisorKnowledgeContext} onChange={(event) => setAdvisorKnowledgeContext(event.target.value)} maxLength={12000} placeholder={uiLang === "vi" ? "Dịch vụ cung cấp gì, đối tượng khách hàng, bảng giá, điều kiện, quy trình tư vấn, điều không được cam kết…" : "Services, target customers, pricing, constraints, sales process and claims that must not be made…"} /><small>{uiLang === "vi" ? "Được đưa trực tiếp vào SOURCE của AI; dùng cho thông tin ngắn, tài liệu dài hãy tải file bên dưới." : "Sent directly as an AI SOURCE; use documents below for longer material."}</small></label>
        <div className="advisorMainActions"><button className="advisorSave" onClick={() => void saveAdvisorConfig()}>{t.saveAdvisor}</button><button className="advisorTest" onClick={() => void testAdvisorApi()}>{t.testApi}</button></div>
      </div>
      <div className="advisorDocuments"><div className="advisorDocHead"><b>{t.advisorDocs}</b><select value={advisorDocCategory} onChange={(event) => setAdvisorDocCategory(event.target.value as "knowledge" | "meeting_log")}><option value="knowledge">{uiLang === "vi" ? "Kiến thức dịch vụ" : "Service knowledge"}</option><option value="meeting_log">{uiLang === "vi" ? "Log cuộc họp" : "Meeting log"}</option></select></div><label className="documentUpload"><input type="file" accept=".docx,.doc,.txt,.md,.csv,.json,.html,.htm" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadAdvisorDocument(file); event.currentTarget.value = ""; }} /><span>＋ {t.uploadDoc}</span></label>{advisorDocs.length > 0 && <div className="documentList">{advisorDocs.map((document) => <article key={document.id}><div><b title={document.name}>{document.name}</b><small>{document.category === "meeting_log" ? "LOG" : "KB"} · {document.chunks} chunks</small></div><button title={t.clear} onClick={() => void deleteAdvisorDocument(document.id)}>×</button></article>)}</div>}</div>
    </details>
    <div className="advisorFeed">{advisorLoading ? <div className="advisorEmpty thinking"><span>◌</span><p>{t.advisorThinking}</p></div> : advisorSuggestions.length === 0 ? <div className="advisorEmpty"><span>✦</span><p>{advisorStatus || t.advisorEmpty}</p></div> : advisorSuggestions.map((suggestion, index) => <article className="suggestionCard" key={`${suggestion.title}-${index}`}><header><b>{suggestion.title}</b><small>{Math.round(suggestion.confidence * 100)}%</small></header><p>{suggestion.answer}</p>{suggestion.reason && <em>{suggestion.reason}</em>}{suggestion.sources.length > 0 && <div className="suggestionSources">{suggestion.sources.map((source) => <span key={source}>{source}</span>)}</div>}<button onClick={() => void navigator.clipboard.writeText(suggestion.answer)}>{t.copyAnswer}</button></article>)}{advisorFollowUp && <article className="followUp"><b>{t.followUp}</b><p>{advisorFollowUp}</p><button onClick={() => void navigator.clipboard.writeText(advisorFollowUp)}>{t.copyAnswer}</button></article>}</div>
    {advisorStatus && advisorSuggestions.length > 0 && <p className="advisorStatus">{advisorStatus}</p>}
  </section>;

  const croppedRegion = screenCaptureMode === "region" && screenRegion && screenRegion.width > 0 && screenRegion.height > 0 ? screenRegion : null;
  const previewAspectRatio = croppedRegion ? screenAspectRatio * croppedRegion.width / croppedRegion.height : screenAspectRatio;
  const zoomSurfaceStyle = croppedRegion ? {
    "--screen-aspect": screenAspectRatio,
    width: `${100 / croppedRegion.width}%`, height: `${100 / croppedRegion.height}%`,
    left: `${-croppedRegion.x / croppedRegion.width * 100}%`, top: `${-croppedRegion.y / croppedRegion.height * 100}%`,
  } as React.CSSProperties : { "--screen-aspect": screenAspectRatio } as React.CSSProperties;

  const screenPanel = <section className={`screenDrawer ${screenRunning ? "live" : ""}`}>
    <header className="screenDrawerHeader"><div className="screenDrawerTitle"><span>03</span><div><h2>{t.screenTitle}</h2><small>{screenNotice}</small><small>{uiLang === "vi" ? "Quét tối thiểu mỗi" : "Minimum scan every"} {desktopRefreshSeconds.toLocaleString(uiLang === "vi" ? "vi-VN" : "en-US")}s{screenScanElapsed !== null ? ` · ${uiLang === "vi" ? "Đang xử lý" : "Processing"} ${screenScanElapsed.toFixed(1)}s` : screenLastLatency !== null ? ` · ${uiLang === "vi" ? "Lượt cuối" : "Last scan"} ${(screenLastLatency / 1000).toFixed(1)}s` : ""}</small></div></div><div className="screenHeaderActions"><button onClick={() => exportDoc(screenFeed, "Screen-OCR")} disabled={!screenFeed.length}>{t.export}</button><button onClick={() => setScreenFeed([])} disabled={!screenFeed.length}>↻ {t.clear}</button><button className="closeScreenDrawer" onClick={() => setScreenPanelOpen(false)} title={uiLang === "vi" ? "Thu gọn dịch màn hình" : "Collapse screen translation"}>›</button></div></header>
    <div className="screenToolbar"><div className="compactLanguagePair"><LanguageSelect value={screenSource} onChange={(value) => { setScreenSource(value); setScreenFeed([]); screenLastTextRef.current = ""; }} disabled={screenRunning} /><b>→</b><LanguageSelect value={screenTarget} onChange={(value) => { setScreenTarget(value); setScreenFeed([]); screenLastTextRef.current = ""; }} disabled={screenRunning} /></div>
      <div className="compactSegment"><button className={screenCaptureMode === "region" ? "selected" : ""} onClick={() => { setScreenCaptureMode("region"); screenGenerationRef.current += 1; setScreenRegion(null); setDraftRegion(null); draftRegionRef.current = null; setScreenOverlays([]); screenLastFrameRef.current = ""; screenLastTextRef.current = ""; setScreenNotice(t.screenSelecting); }}>{t.screenRegionMode}</button><button className={screenCaptureMode === "full" ? "selected" : ""} onClick={() => { setScreenCaptureMode("full"); screenGenerationRef.current += 1; setScreenRegion(null); setDraftRegion(null); draftRegionRef.current = null; setScreenOverlays([]); screenLastFrameRef.current = ""; screenLastTextRef.current = ""; setScreenNotice(t.screenWatching); }}>{t.screenFullMode}</button></div>
      <div className="compactSegment processorSegment"><button className={screenProcessor === "cpu" ? "selected" : ""} onClick={() => setScreenProcessor("cpu")} disabled={screenRunning || screenPreparing}>CPU</button><button className={screenProcessor === "gpu" ? "selected" : ""} onClick={() => setScreenProcessor("gpu")} disabled={screenRunning || screenPreparing}>GPU</button></div>
      <button className={`screenRunButton ${screenRunning ? "stop" : ""}`} onClick={screenRunning ? stopScreen : startScreen} disabled={screenPreparing}>{screenRunning ? "■" : screenPreparing ? "◌" : "▣"}<span>{screenRunning ? t.screenStop : screenPreparing ? t.preparing : t.screenStart}</span></button>
    </div>
    <details className="screenAdvanced"><summary>{uiLang === "vi" ? "Cài đặt OCR & overlay" : "OCR & overlay settings"}<span>{screenRunning ? `OCR đang chạy: ${screenActualProcessor.toUpperCase()}` : `OCR đã chọn: ${screenProcessor.toUpperCase()} · chưa chạy`}</span></summary><div className="screenAdvancedGrid">
      <label className={`hotkeyCapture ${desktopScreenHotkeyCapturing ? "capturing" : ""}`}><span>{t.desktopScreenHotkeyLabel}</span><input value={desktopScreenHotkeyCapturing ? t.hotkeyCapture : desktopScreenHotkey} readOnly onFocus={() => setDesktopScreenHotkeyCapturing(true)} onClick={() => setDesktopScreenHotkeyCapturing(true)} onKeyDown={captureDesktopScreenHotkey} /></label>
      <label className={`hotkeyCapture ${desktopExitHotkeyCapturing ? "capturing" : ""}`}><span>{t.desktopExitHotkey}</span><input value={desktopExitHotkeyCapturing ? t.hotkeyCapture : desktopExitHotkey} readOnly onFocus={() => setDesktopExitHotkeyCapturing(true)} onClick={() => setDesktopExitHotkeyCapturing(true)} onKeyDown={captureDesktopExitHotkey} /></label>
      <label><span>{t.desktopFontSize}</span><input type="number" min="8" max="48" step="1" value={desktopScreenFontSize} onChange={(event) => setDesktopScreenFontSize(Math.max(8, Math.min(48, Number(event.target.value) || 8)))} /></label>
      <label><span>{t.desktopRefresh}</span><input type="number" min="0.25" max="10" step="0.25" value={desktopRefreshSeconds} onChange={(event) => setDesktopRefreshSeconds(Math.max(0.25, Math.min(10, Number(event.target.value) || 1)))} /><small>{uiLang === "vi" ? "Áp dụng cho quét web và overlay Windows. OCR + dịch lâu hơn thì lượt sau phải chờ; giảm số này không làm model chạy nhanh hơn." : "Applies to web scanning and Windows overlay. A scan waits if OCR + translation takes longer; lowering this does not speed up the model."}</small></label>
      <label><span>{t.desktopOpacity} · {Math.round(desktopOverlayOpacity * 100)}%</span><input type="range" min="20" max="100" step="1" value={Math.round(desktopOverlayOpacity * 100)} onChange={(event) => setDesktopOverlayOpacity(Number(event.target.value) / 100)} /></label>
      <label className="compactToggle"><input type="checkbox" checked={desktopScreenContinuous} onChange={(event) => setDesktopScreenContinuous(event.target.checked)} /><span>{t.desktopContinuous}</span></label>
      <label className="compactToggle"><input type="checkbox" checked={desktopStatusVisible} onChange={(event) => setDesktopStatusVisible(event.target.checked)} /><span>{t.desktopShowStatus}</span></label>
      <label><span>{uiLang === "vi" ? "Màu chữ" : "Text color"}</span><input type="color" value={overlayForeground} onChange={(event) => setOverlayForeground(event.target.value)} /></label>
      <label><span>{uiLang === "vi" ? "Màu nền chữ" : "Text background"}</span><input type="color" value={overlayBackground} onChange={(event) => setOverlayBackground(event.target.value)} /></label>
      <p className="overlayHelp">{uiLang === "vi" ? "Cỡ chữ, màu và độ mờ áp dụng ngay cho preview web; Lưu để dùng cho overlay desktop. Chữ tự thu nhỏ nếu ô OCR quá hẹp." : "Font, colors and opacity update the web preview; save to apply to desktop. Text shrinks to fit small OCR boxes."}</p>
      <button className="screenHotkeySave" onClick={() => void saveHotkeySettings("screen")}>⌨ {t.hotkeySave}</button><p className="overlayHelp">{hotkeyNotices.screen}</p>
    </div></details>
    <div className="screenPreviewArea">
      <div ref={screenStageRef} className={`captureStage ${screenRunning ? "hasVideo" : ""} ${screenRunning && screenCaptureMode === "region" && !screenRegion ? "active" : ""}`} style={{ "--preview-aspect": previewAspectRatio } as React.CSSProperties} onPointerDown={screenPointerDown} onPointerMove={screenPointerMove} onPointerUp={screenPointerUp} onPointerCancel={screenPointerUp}>
        <div className="screenImageViewport"><div ref={screenSurfaceRef} className={`screenImageSurface ${croppedRegion ? "cropped" : ""}`} style={zoomSurfaceStyle}>
          <video ref={screenVideoRef} autoPlay muted playsInline onLoadedMetadata={(event) => { const video = event.currentTarget; if (video.videoWidth && video.videoHeight) setScreenAspectRatio(video.videoWidth / video.videoHeight); }} />
          {screenOverlays.map((overlay, index) => <FittedScreenOverlay overlay={overlay} fontSize={desktopScreenFontSize} foreground={overlayForeground} background={overlayBackground} opacity={desktopOverlayOpacity} key={`${overlay.source}-${index}`} />)}
          {draftRegion && <div className="captureRegion" style={{ left: `${draftRegion.x * 100}%`, top: `${draftRegion.y * 100}%`, width: `${draftRegion.width * 100}%`, height: `${draftRegion.height * 100}%` }} />}
        </div></div>
        {!screenRunning && <div className="capturePlaceholder"><b>▣</b><span>{t.screenStart}</span></div>}
        {screenRunning && <button className="screenFullscreenButton" title={screenFullscreen ? t.screenExitFullscreen : t.screenFullscreen} aria-label={screenFullscreen ? t.screenExitFullscreen : t.screenFullscreen} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); void toggleScreenFullscreen(); }}>{screenFullscreen ? "×" : "⛶"}</button>}
      </div>
      <canvas ref={screenCanvasRef} hidden />
      <div className="screenPreviewFooter"><span>{croppedRegion ? (uiLang === "vi" ? "Vùng đã chọn · crop và phóng vừa khung" : "Selected region · cropped and fitted") : t.screenHelp}</span><button onClick={() => { screenGenerationRef.current += 1; setScreenRegion(null); setDraftRegion(null); draftRegionRef.current = null; setScreenOverlays([]); screenLastFrameRef.current = ""; screenLastTextRef.current = ""; setScreenNotice(t.screenSelecting); }} disabled={!screenRunning || screenCaptureMode !== "region" || !screenRegion}>{t.screenReset}</button></div>
      {screenRunning && croppedRegion && <div className="screenThumbnail" style={{ "--screen-aspect": screenAspectRatio } as React.CSSProperties}><span>{uiLang === "vi" ? "Vị trí vùng đã chọn trong toàn màn hình" : "Selected area in full screen"}</span><div><video ref={screenThumbVideoRef} autoPlay muted playsInline /><i style={{ left: `${croppedRegion.x * 100}%`, top: `${croppedRegion.y * 100}%`, width: `${croppedRegion.width * 100}%`, height: `${croppedRegion.height * 100}%` }} /></div></div>}
    </div>
    <details className="screenHistory"><summary>{uiLang === "vi" ? `Lịch sử OCR (${screenFeed.length})` : `OCR history (${screenFeed.length})`}</summary><div className="compactFeed">{screenFeed.length === 0 ? <div className="compactEmpty"><span>文</span><p>{t.screenEmpty}</p></div> : screenFeed.map((item) => <article key={item.id} className="compactFeedItem done"><time>{feedTime(item)}</time><i className="turnBar" /><div className="turnCopy"><p>{item.source}</p><p>{item.translation}</p></div><div className="turnMeta">{item.latencyMs !== undefined && <small>{(item.latencyMs / 1000).toFixed(1)}s</small>}</div></article>)}</div></details>
  </section>;

  return <main className="shell">
    <header className="topbar dashboardTopbar">
      <div className="brand"><span className="brandMark">S</span><div><strong>SpeakBridge V2</strong><small>{t.twoWay}</small></div></div>
      <nav className="workspaceTabs" aria-label={uiLang === "vi" ? "Chế độ làm việc" : "Workspace tabs"}>
        <button type="button" className={`workspaceTabBtn ${activeTab === "live" ? "active" : ""}`} onClick={() => setActiveTab("live")}>
          <span>01–03</span>
          <b>{uiLang === "vi" ? "Phiên dịch Live & Màn hình" : "Live & Screen Interpreter"}</b>
        </button>
        <button type="button" className={`workspaceTabBtn ${activeTab === "videodub" ? "active" : ""}`} onClick={() => setActiveTab("videodub")}>
          <span>04</span>
          <b>{uiLang === "vi" ? "Thuyết minh Video / TikTok" : "Video / TikTok Dubbing"}</b>
        </button>
      </nav>
      <div className="headerActions"><div className={`health ${online ? "online" : "offline"}`}><span />{online ? engineInfo || t.online : t.offline}</div><button className="settingsButton" onClick={() => setSettingsOpen(true)}>⚙ {t.settings}</button></div>
    </header>
    <section className="sharedToolbar" hidden={activeTab !== "live"}><div className="sharedModeLabel"><span>01</span><div><b>{uiLang === "vi" ? "NHẬN DẠNG" : "RECOGNITION"}</b><small>{uiLang === "vi" ? "Áp dụng cả 02A + 02B" : "Applies to 02A + 02B"}</small></div></div><div className="compactSegment sharedMode"><button className={mode === "fast" ? "selected" : ""} onClick={() => setMode("fast")} disabled={anyRunning}>FAST<small>Turbo</small></button><button className={mode === "quality" ? "selected" : ""} onClick={() => setMode("quality")} disabled={anyRunning}>QUALITY<small>Large-v3</small></button></div><button className="contextButton" onClick={() => setContextOpen(true)}>{uiLang === "vi" ? "Ngữ cảnh & Glossary" : "Context & Glossary"}</button><button className={`screenDrawerToggle ${screenPanelOpen ? "active" : ""}`} onClick={() => setScreenPanelOpen((open) => !open)}>▣ <span>{screenPanelOpen ? (uiLang === "vi" ? "Ẩn dịch màn hình" : "Hide screen translation") : (uiLang === "vi" ? "Mở dịch màn hình" : "Open screen translation")}</span></button></section>
    <div ref={dashboardRef} hidden={activeTab !== "live"} className={`dashboardLayout ${screenPanelOpen ? "screenOpen" : "screenClosed"}`} style={{ "--screen-panel-width": `${screenPanelWidth}%` } as React.CSSProperties}><section className="conversationStack">{transcriptBoard("incoming", inFeed, inSource, inTarget, inListening)}{transcriptBoard("outgoing", outFeed, outSource, outTarget, outListening)}{advisorBoard}</section><button hidden={!screenPanelOpen} className="dashboardResizer" onPointerDown={beginDashboardResize} aria-label={uiLang === "vi" ? "Kéo để đổi kích thước hai cột" : "Drag to resize columns"} /><div className="screenDrawerSlot" hidden={!screenPanelOpen}>{screenPanel}</div></div>
    <VideoDubPanel uiLang={uiLang} online={online} voiceOptions={voiceOptions} defaultMode={mode} hidden={activeTab !== "videodub"} />
    <footer><span>Whisper · Hy-MT2 7B · VieNeu · Kokoro · RapidOCR · Demucs · WASAPI</span><span>{online ? engineInfo : "Backend offline · SPEAKBRIDGE.bat → Start"}</span></footer>
    {contextOpen && <div className="settingsOverlay contextOverlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setContextOpen(false); }}><section className="settingsDialog contextDialog" role="dialog" aria-modal="true" aria-label={t.context} ><div className="settingsHead"><h2>{t.context} & Glossary</h2><button onClick={() => setContextOpen(false)}>{t.close}</button></div><div className="contextFields"><label><span>{t.context}</span><textarea value={meetingContext} onChange={(event) => setMeetingContext(event.target.value)} disabled={anyRunning} /><small>{t.contextHelp}</small></label><label><span>{t.glossary}</span><textarea value={glossary} onChange={(event) => setGlossary(event.target.value)} disabled={anyRunning} /><small>{t.glossaryHelp}</small></label></div><p>{uiLang === "vi" ? "Thay đổi áp dụng khi bắt đầu lại luồng. FAST: Whisper Turbo · beam 1. QUALITY: large-v3 · beam 5, chậm hơn; không đảm bảo mọi câu đều đúng. Cả hai dùng cùng Hy-MT2." : "Changes apply when streams restart. FAST: Whisper Turbo, beam 1. QUALITY: large-v3, beam 5; slower, not a guarantee of accuracy. Both share Hy-MT2."}</p></section></div>}
    {settingsOpen && <div className="settingsOverlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false); }}>
      <section className="settingsDialog">
        <div className="settingsHead"><h2>⚙ {t.settings}</h2><button onClick={() => setSettingsOpen(false)}>×</button></div>
        <label className="field"><span>{t.uiLanguage}</span><select value={uiLang} onChange={(e) => setUiLang(e.target.value as UiLanguage)}><option value="vi">Tiếng Việt</option><option value="en">English</option></select></label>
        <div className="translatorInfo"><span>{t.translator}</span><b>Hy-MT2 7B Q6</b><small>{uiLang === "vi" ? "Model dịch đang dùng · FAST / QUALITY chỉ thay Whisper nhận dạng, không thay model dịch." : "Active translation model · FAST / QUALITY changes Whisper recognition only."}</small></div>
        <details className="advisorApiSettings"><summary>✦ {t.advisorTitle} · API</summary><p>{uiLang === "vi" ? "Key chỉ lưu trong config/advisor.local.json trên máy và đã được Git bỏ qua. 9Router mặc định chạy tại localhost:20128." : "The key is stored only in local config/advisor.local.json and ignored by Git. 9Router defaults to localhost:20128."}</p>
          <label className="field"><span>{t.apiProvider}</span><select value={advisorProvider} onChange={(event) => { const provider = event.target.value; setAdvisorProvider(provider); setAdvisorBaseUrl(ADVISOR_PROVIDERS[provider].baseUrl); setAdvisorModel(ADVISOR_PROVIDERS[provider].model); }}><option value="openai">OpenAI API</option><option value="anthropic">Anthropic Claude</option><option value="deepseek">DeepSeek</option><option value="9router">9Router</option><option value="custom">Custom OpenAI-compatible</option></select></label>
          <label className="field"><span>{t.apiBase}</span><input value={advisorBaseUrl} onChange={(event) => setAdvisorBaseUrl(event.target.value)} spellCheck={false} /></label>
          <label className="field"><span>{t.apiModel}</span><input value={advisorModel} onChange={(event) => setAdvisorModel(event.target.value)} placeholder={advisorProvider === "9router" ? "auto / combo alias / provider model" : "model-id"} spellCheck={false} /></label>
          <label className="field"><span>{t.apiKey}</span><input type="password" value={advisorApiKey} onChange={(event) => setAdvisorApiKey(event.target.value)} placeholder={advisorHasKey ? (uiLang === "vi" ? "Đã lưu · để trống để giữ nguyên" : "Saved · leave blank to keep") : "sk-…"} autoComplete="off" /><small>{advisorProvider === "openai" && (uiLang === "vi" ? "OpenAI API dùng billing/key riêng; không sử dụng quota Codex trong ChatGPT." : "OpenAI API uses separate billing/key; it does not use ChatGPT Codex quota.")}</small></label>
          <div className="advisorApiActions"><button onClick={() => void saveAdvisorConfig()}>{t.saveAdvisor}</button><button onClick={() => void testAdvisorApi()}>{t.testApi}</button></div>{advisorStatus && <p className="notice">{advisorStatus}</p>}
        </details>
        <div className="helperStatus">          <button className="startButton secondary" onClick={() => void checkHelperStatus()}>{uiLang === "vi" ? "Kiểm tra helper / phím tắt" : "Check helper / shortcuts"}</button><p className="notice" role="status">{helperNotice}</p></div>
        <div className="helperOverlaySetting"><label className="checkField"><input type="checkbox" checked={desktopStatusVisible} onChange={(event) => { const visible = event.target.checked; setDesktopStatusVisible(visible); void saveHotkeySettings("helper", {show_status_overlay:visible}); }} /><span>{uiLang === "vi" ? "Hiện tiến trình helper trên màn hình" : "Show helper progress on screen"}</span></label><small>{uiLang === "vi" ? "Áp dụng và lưu ngay. Tắt chỉ ẩn thanh trạng thái; các phím tắt và bản dịch vẫn hoạt động." : "Saved and applied immediately. Hides only the status bar; shortcuts and translations continue."}</small><p className="notice" role="status">{hotkeyNotices.helper}</p></div>
        <div className="hotkeySettings" onChange={() => markHotkeyDirty("voice")}>
          <h3><span className="shortcutNumber">01</span>{uiLang === "vi" ? "Nói → nhập chữ" : "Voice → type text"}</h3><p>{t.hotkeyHelp}</p>
          <label className={`field hotkeyCapture ${hotkeyCapturing ? "capturing" : ""}`}><span>{t.hotkeyLabel}</span><input value={hotkeyCapturing ? t.hotkeyCapture : hotkey} readOnly onFocus={() => setHotkeyCapturing(true)} onClick={() => setHotkeyCapturing(true)} onKeyDown={captureHotkey} /></label>
          <label className="field"><span>{t.hotkeyMic}</span><select value={hotkeyMicrophone} onChange={(e) => setHotkeyMicrophone(e.target.value)}><option value="__default__">{t.defaultMic}</option>{hotkeyMicrophones.map((device) => <option key={device} value={device}>{device}</option>)}</select><small>{uiLang === "vi" ? "Hãy chọn USB Condenser; không chọn CABLE Output." : "Select the USB condenser microphone; do not select CABLE Output."}</small></label>
          <div className="languageGrid"><label className="field"><span>{t.sourceLanguage}</span><LanguageSelect value={hotkeySource} onChange={setHotkeySource} allowAuto /></label><label className="field"><span>{t.targetLanguage}</span><LanguageSelect value={hotkeyTarget} onChange={setHotkeyTarget} disabled={!hotkeyTranslate} /></label></div>
          <label className="checkField"><input type="checkbox" checked={hotkeyTranslate} onChange={(e) => setHotkeyTranslate(e.target.checked)} /><span>{t.hotkeyTranslate}</span></label>
          <button className="startButton secondary" onClick={() => void saveHotkeySettings("voice")}>{t.hotkeySave}</button>{hotkeyNotices.voice && <p className="notice" role="status">{hotkeyNotices.voice}</p>}
        </div>
        <div className="hotkeySettings" onChange={() => markHotkeyDirty("text")}>
          <h3><span className="shortcutNumber">02</span>{uiLang === "vi" ? "Dịch chữ trong ô chat" : "Translate typed chat"}</h3>
          <label className={`field hotkeyCapture ${textHotkeyCapturing ? "capturing" : ""}`}><span>{t.textHotkeyLabel}</span><input value={textHotkeyCapturing ? t.hotkeyCapture : textTranslateHotkey} readOnly onFocus={() => setTextHotkeyCapturing(true)} onClick={() => setTextHotkeyCapturing(true)} onKeyDown={captureTextTranslateHotkey} /><small>{t.textHotkeyHelp}</small></label>
          <div className="languageGrid"><label className="field"><span>{uiLang === "vi" ? "Ngôn ngữ chữ gốc" : "Typed text language"}</span><LanguageSelect value={textSource} onChange={setTextSource} /></label><label className="field"><span>{uiLang === "vi" ? "Dịch chữ thành" : "Translate typed text to"}</span><LanguageSelect value={textTarget} onChange={setTextTarget} /></label></div>
          <button className="startButton secondary" onClick={() => void saveHotkeySettings("text")}>{t.hotkeySave}</button>{hotkeyNotices.text && <p className="notice" role="status">{hotkeyNotices.text}</p>}
        </div>
        <div className="hotkeySettings" onChange={() => { markHotkeyDirty("read"); setScreenReadTestNotice(""); }}>
          <h3><span className="shortcutNumber">03</span>{t.screenReadTitle}</h3><p>{t.screenReadHelp}</p>
          <label className="field"><span>{uiLang === "vi" ? "Loa / tai nghe đọc chữ" : "Read-aloud speaker / headphones"}</span><select value={screenReadOutputDevice} onChange={(event) => { setScreenReadOutputDevice(event.target.value); setScreenReadTestNotice(""); }}><option value="__default__">{uiLang === "vi" ? "Thiết bị phát mặc định Windows" : "Windows default output"}</option>{!speakerDevices.includes(screenReadOutputDevice) && screenReadOutputDevice !== "__default__" && <option value={screenReadOutputDevice}>{screenReadOutputDevice} ({uiLang === "vi" ? "chưa kết nối" : "disconnected"})</option>}{speakerDevices.map((device) => <option key={device} value={device}>{device}</option>)}</select><small>{uiLang === "vi" ? "Chọn tai nghe/loa bạn đang nghe. Đầu phát này chỉ dùng để đọc chữ, không đổi đầu ra 02B vào VB-CABLE." : "Choose the headphones/speakers you listen on. This output only applies to read-aloud and does not change panel 02B's VB-CABLE output."}</small></label>
          <button className="startButton secondary" disabled={screenReadTesting} onClick={() => void testScreenReadOutput()}>{uiLang === "vi" ? "Thử âm thanh" : "Test sound"}</button>{!screenReadTestIsVoice && screenReadTestNotice && <p className="notice" role="status">{screenReadTestNotice}</p>}
          <label className={`field hotkeyCapture ${screenReadHotkeyCapturing ? "capturing" : ""}`}><span>{t.screenReadHotkey}</span><input value={screenReadHotkeyCapturing ? t.hotkeyCapture : screenReadHotkey} readOnly onFocus={() => setScreenReadHotkeyCapturing(true)} onClick={() => setScreenReadHotkeyCapturing(true)} onKeyDown={captureScreenReadHotkey} /></label>
          <label className="field"><span>{t.screenReadMode}</span><select value={screenReadMode} onChange={(event) => setScreenReadMode(event.target.value as "source" | "translation")}><option value="source">{t.screenReadOriginal}</option><option value="translation">{t.screenReadTranslation}</option></select></label>
          <div className="languageGrid"><label className="field"><span>{t.screenReadSource}</span><LanguageSelect value={screenReadSource} onChange={setScreenReadSource} allowAuto /></label>{screenReadMode === "translation" && <label className="field"><span>{t.screenReadTarget}</span><LanguageSelect value={screenReadTarget} onChange={setScreenReadTarget} /></label>}</div>
          {screenReadMode === "source" && <p className="readModeNote">{uiLang === "vi" ? "Đọc nguyên văn bằng ngôn ngữ chữ đã chọn — không dịch." : "Read the original in the selected source language — no translation."}</p>}
          {screenReadMode === "source" && screenReadSource === "auto" && <label className="field"><span>{uiLang === "vi" ? "Cài giọng cho ngôn ngữ (Auto)" : "Configure voice for language (Auto)"}</span><LanguageSelect value={screenReadAutoVoiceLanguage} onChange={setScreenReadAutoVoiceLanguage} /><small>{uiLang === "vi" ? "Auto nhận ngôn ngữ từ chữ; giọng được lưu riêng cho từng ngôn ngữ." : "Auto detects the text language; voice choices are saved separately for each language."}</small></label>}
          <label className="field"><span>{uiLang === "vi" ? "Giọng đọc chữ đã bôi đen" : "Selected-text voice"}</span><select value={screenReadVoices[screenReadVoiceLanguage] || ""} onChange={(event) => setScreenReadVoices((previous) => ({...previous, [screenReadVoiceLanguage]:event.target.value}))} disabled={screenReadTesting || !voiceOptions[screenReadVoiceLanguage]?.length}>{(voiceOptions[screenReadVoiceLanguage] || []).map((option) => <option key={option.id} value={option.id} disabled={!option.installed}>{option.label}{option.installed ? "" : (uiLang === "vi" ? " · thiếu tệp" : " · missing files")}</option>)}</select></label>
          <button className="startButton secondary" disabled={screenReadTesting || !voiceOptions[screenReadVoiceLanguage]?.some((option) => option.id === screenReadVoices[screenReadVoiceLanguage] && option.installed)} onClick={() => void testScreenReadOutput(true)}>{uiLang === "vi" ? "Thử giọng đọc" : "Test selected voice"}</button>{screenReadTestIsVoice && screenReadTestNotice && <p className="notice" role="status">{screenReadTestNotice}</p>}
          <small>{t.screenReadProcessor}</small>
          <button className="startButton secondary" onClick={() => void saveHotkeySettings("read")}>{t.hotkeySave}</button>{hotkeyNotices.read && <p className="notice" role="status">{hotkeyNotices.read}</p>}
        </div>
        <div className="modelStatus"><h3>{uiLang === "vi" ? "Tệp model đã kiểm tra" : "Verified model files"} · {modelAssets.filter((asset) => asset.installed).length}/{modelAssets.length}</h3><p>{uiLang === "vi" ? "7 bộ model có thể dùng chung thư mục. Whisper/Kokoro nằm trong cache Hugging Face; OCR Hàn nằm chung RapidOCR." : "Seven assets can share folders. Whisper/Kokoro use the Hugging Face cache; Korean OCR shares RapidOCR."}</p>{modelAssets.map((asset) => <article key={asset.name}><span className={asset.installed ? "installed" : "missing"}>{asset.installed ? "✓" : "!"}</span><div><b>{asset.name}</b><small>{asset.role} · {asset.processor} · {asset.size_gb} GB</small><code title={asset.path}>{asset.path}</code>{!asset.installed && <small className="missingFiles">{uiLang === "vi" ? "Thiếu tệp:" : "Missing:"} {asset.missing_files?.join(", ")}</small>}<button className="modelFolderButton" onClick={() => void openModelFolder(asset.name)}>{uiLang === "vi" ? "Mở thư mục" : "Open folder"} ↗</button></div></article>)}<p role="status">{modelFolderNotice}</p><p>{uiLang === "vi" ? "Cache cố định:" : "Pinned cache:"} <code>{modelCacheRoot || "—"}</code></p><small>{uiLang === "vi" ? "Kiểm tra tệp có đủ và không rỗng, chưa phải kiểm chứng chất lượng model. Không tự tải thêm model." : "Checks required files are present and non-empty, not model quality. No automatic downloads."}</small></div>
        <p className="storageNote">{t.storage}</p><button className="startButton" onClick={() => setSettingsOpen(false)}>{t.close}</button>
      </section>
    </div>}
  </main>;
}
