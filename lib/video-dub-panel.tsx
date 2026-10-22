"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type VideoDubVoiceOption = {
  id: string;
  label: string;
  installed: boolean;
  error: string;
};

type DubChunkInfo = {
  i: number;
  start: number;
  end: number;
  ready: boolean;
  timing?: Record<string, number> | null;
};

type DubSubCue = {
  start: number;
  end: number;
  zh: string;
  vi: string;
};

type StoryBible = {
  synopsis?: string;
  genre_tone?: string;
  characters?: Array<{ zh?: string; vi?: string; note?: string; src?: string; tgt?: string }>;
  terms?: Record<string, string>;
};

type DubJobSnapshot = {
  job_id: string;
  title: string;
  url: string;
  state: "loading" | "running" | "done" | "error" | "cancelled";
  stage: string;
  error: string | null;
  duration: number;
  has_video: boolean;
  source_language: string;
  target_language: string;
  voice: string;
  bgm_mode: string;
  translator_engine: string;
  chunks: DubChunkInfo[];
  subs: DubSubCue[];
  bible: StoryBible;
  sample_rate: number;
};

const HTTP = "http://127.0.0.1:8765";

const DUB_LANGUAGES = [
  ["vi", "Tiếng Việt", "Vietnamese"],
  ["en", "Tiếng Anh", "English"],
  ["zh", "Tiếng Trung", "Chinese"],
  ["ja", "Tiếng Nhật", "Japanese"],
  ["ko", "Tiếng Hàn", "Korean"],
] as const;

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "00:00";
  const total = Math.floor(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function VideoDubPanel({
  uiLang,
  online,
  voiceOptions,
  defaultMode,
  hidden = false,
}: {
  uiLang: "vi" | "en";
  online: boolean;
  voiceOptions: Record<string, VideoDubVoiceOption[]>;
  defaultMode: "fast" | "quality";
  hidden?: boolean;
}) {
  const [urlInput, setUrlInput] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("vi");
  const [voice, setVoice] = useState("F1");
  const [engineMode, setEngineMode] = useState<"local" | "llm">("local");
  const [bgmMode, setBgmMode] = useState<"mute" | "duck" | "demucs">("mute");
  const [job, setJob] = useState<DubJobSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [waitingChunkIndex, setWaitingChunkIndex] = useState<number | null>(null);
  const [subFontSize, setSubFontSize] = useState(22);
  const [showBilingualSubs, setShowBilingualSubs] = useState(true);
  const [subBottomPercent, setSubBottomPercent] = useState(8);
  const [dubVolume, setDubVolume] = useState(100);
  const [origVideoVolume, setOrigVideoVolume] = useState(0);
  const [showExtensionGuide, setShowExtensionGuide] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const currentSourceRef = useRef<{
    node: AudioBufferSourceNode;
    chunkIndex: number;
    startedAtCtx: number;
    offsetInChunk: number;
    rate: number;
  } | null>(null);
  const buffersRef = useRef<Map<number, AudioBuffer>>(new Map());
  const fetchingChunksRef = useRef<Set<number>>(new Set());
  const waitingForChunkRef = useRef(false);
  const jobRef = useRef<DubJobSnapshot | null>(null);
  const lastSeekPostedRef = useRef<{ index: number; at: number }>({ index: -1, at: 0 });
  const subDragRef = useRef<{ startY: number; startBottom: number } | null>(null);

  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  const effectiveVoice = useMemo(() => {
    const list = voiceOptions[targetLang] || [];
    if (!list.length) return voice;
    if (list.some((item) => item.id === voice && item.installed)) return voice;
    const preferred =
      targetLang === "vi"
        ? list.find((item) => item.id === "F1" && item.installed) ||
          list.find((item) => item.id === "M1" && item.installed)
        : list.find((item) => item.installed);
    return preferred ? preferred.id : voice;
  }, [targetLang, voice, voiceOptions]);

  const stopWebAudioNode = useCallback(() => {
    if (currentSourceRef.current) {
      try {
        currentSourceRef.current.node.onended = null;
        currentSourceRef.current.node.stop();
        currentSourceRef.current.node.disconnect();
      } catch {
        // Ignore already-stopped source errors
      }
      currentSourceRef.current = null;
    }
  }, []);

  const resetAudioEngine = useCallback(() => {
    stopWebAudioNode();
    buffersRef.current.clear();
    fetchingChunksRef.current.clear();
    waitingForChunkRef.current = false;
    setWaitingChunkIndex(null);
  }, [stopWebAudioNode]);

  const ensureAudioContext = useCallback(() => {
    if (!audioCtxRef.current) {
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioContextClass();
      const gain = ctx.createGain();
      gain.gain.value = dubVolume / 100;
      gain.connect(ctx.destination);
      audioCtxRef.current = ctx;
      gainNodeRef.current = gain;
    }
    if (audioCtxRef.current.state === "suspended") {
      void audioCtxRef.current.resume().catch(() => {});
    }
    return audioCtxRef.current;
  }, [dubVolume]);

  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = dubVolume / 100;
    }
  }, [dubVolume]);

  useEffect(() => {
    if (videoRef.current) {
      const targetVol = Math.max(0, Math.min(1, origVideoVolume / 100));
      videoRef.current.volume = targetVol;
      videoRef.current.muted = origVideoVolume === 0;
    }
  }, [origVideoVolume, job?.job_id]);

  const fetchChunkBuffer = useCallback(
    async (jobId: string, chunkIndex: number) => {
      if (buffersRef.current.has(chunkIndex) || fetchingChunksRef.current.has(chunkIndex)) {
        return;
      }
      fetchingChunksRef.current.add(chunkIndex);
      try {
        const ctx = ensureAudioContext();
        const response = await fetch(`${HTTP}/jobs/${jobId}/chunks/${chunkIndex}.wav`);
        if (!response.ok) return;
        const raw = await response.arrayBuffer();
        const decoded = await ctx.decodeAudioData(raw.slice(0));
        if (jobRef.current?.job_id === jobId) {
          buffersRef.current.set(chunkIndex, decoded);
        }
      } catch {
        // Ignore transient decode or network error
      } finally {
        fetchingChunksRef.current.delete(chunkIndex);
      }
    },
    [ensureAudioContext]
  );

  const syncPlayback = useCallback(() => {
    const video = videoRef.current;
    const activeJob = jobRef.current;
    if (!video || !activeJob || !activeJob.chunks.length) {
      stopWebAudioNode();
      return;
    }

    // Strictly enforce original video volume/mute on every tick so raw audio never leaks when set to 0%
    const targetMuted = origVideoVolume === 0;
    const targetVol = Math.max(0, Math.min(1, origVideoVolume / 100));
    if (video.muted !== targetMuted) video.muted = targetMuted;
    if (Math.abs(video.volume - targetVol) > 0.01) video.volume = targetVol;

    const t = video.currentTime;
    setCurrentTime(t);

    const chunk = activeJob.chunks.find((c) => t >= c.start && t < c.end - 0.02);
    if (!chunk) {
      stopWebAudioNode();
      return;
    }

    for (const candidate of activeJob.chunks) {
      if (candidate.i >= chunk.i && candidate.i <= chunk.i + 2 && candidate.ready) {
        void fetchChunkBuffer(activeJob.job_id, candidate.i);
      }
    }

    const hasBuffer = buffersRef.current.has(chunk.i);

    if (!hasBuffer) {
      stopWebAudioNode();
      if (!video.paused && !video.ended && activeJob.state !== "error") {
        waitingForChunkRef.current = true;
        setWaitingChunkIndex(chunk.i);
        video.pause();
      }
      if (chunk.ready) {
        void fetchChunkBuffer(activeJob.job_id, chunk.i);
      }
      return;
    }

    if (waitingForChunkRef.current && video.paused && !video.ended) {
      waitingForChunkRef.current = false;
      setWaitingChunkIndex(null);
      void video.play().catch(() => {});
      return;
    }

    if (video.paused || video.ended) {
      stopWebAudioNode();
      return;
    }

    setWaitingChunkIndex(null);
    const ctx = ensureAudioContext();
    const buffer = buffersRef.current.get(chunk.i)!;
    const rate = video.playbackRate || 1;
    const targetOffset = Math.max(0, t - chunk.start);

    const playing = currentSourceRef.current;
    if (playing && playing.chunkIndex === chunk.i) {
      const elapsedCtx = (ctx.currentTime - playing.startedAtCtx) * playing.rate;
      const actualOffset = playing.offsetInChunk + elapsedCtx;
      if (Math.abs(actualOffset - targetOffset) <= 0.12 && Math.abs(playing.rate - rate) < 0.01) {
        return;
      }
    }

    stopWebAudioNode();
    if (targetOffset >= buffer.duration - 0.02) return;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = rate;
    source.connect(gainNodeRef.current || ctx.destination);
    source.start(0, targetOffset);
    currentSourceRef.current = {
      node: source,
      chunkIndex: chunk.i,
      startedAtCtx: ctx.currentTime,
      offsetInChunk: targetOffset,
      rate,
    };
  }, [ensureAudioContext, fetchChunkBuffer, origVideoVolume, stopWebAudioNode]);

  // Poll job status
  useEffect(() => {
    if (!job) return;
    const isTerminal = ["done", "error", "cancelled"].includes(job.state);
    if (isTerminal) {
      for (const c of job.chunks) {
        if (c.ready && !buffersRef.current.has(c.i) && c.i < 3) {
          void fetchChunkBuffer(job.job_id, c.i);
        }
      }
      return;
    }

    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${HTTP}/jobs/${job.job_id}`);
        if (!res.ok) return;
        const data: DubJobSnapshot = await res.json();
        if (cancelled) return;
        setJob(data);
        for (const c of data.chunks) {
          if (c.ready && !buffersRef.current.has(c.i)) {
            const vTime = videoRef.current?.currentTime ?? 0;
            if (c.end >= vTime - 2 && c.start <= vTime + 35) {
              void fetchChunkBuffer(data.job_id, c.i);
            }
          }
        }
      } catch {
        // Ignore transient poll errors
      }
    }, 900);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [fetchChunkBuffer, job]);

  // Periodic sync loop while a job is loaded (50ms precision matching browser extension)
  useEffect(() => {
    if (!job) return;
    const timer = window.setInterval(() => {
      syncPlayback();
    }, 50);
    return () => window.clearInterval(timer);
  }, [job, syncPlayback]);

  // Auto-attach active job on initial load if one is already running on the backend
  useEffect(() => {
    if (!online || jobRef.current) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`${HTTP}/jobs/active`);
        if (!res.ok) return;
        const payload = await res.json();
        if (!cancelled && payload.active && payload.job_id && !jobRef.current) {
          setJob(payload);
        }
      } catch {
        // Ignore initial check error
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [online]);

  useEffect(() => {
    return () => {
      stopWebAudioNode();
      void audioCtxRef.current?.close().catch(() => {});
    };
  }, [stopWebAudioNode]);

  const startUrlJob = useCallback(async () => {
    if (!online) {
      setNotice(uiLang === "vi" ? "Backend đang offline." : "Backend is offline.");
      return;
    }
    const trimmed = urlInput.trim();
    if (!trimmed) {
      setNotice(
        uiLang === "vi"
          ? "Hãy dán link TikTok, Douyin, YouTube, Bilibili hoặc URL video."
          : "Please paste a TikTok, Douyin, YouTube, Bilibili or direct video URL."
      );
      return;
    }
    setBusy(true);
    setNotice(
      uiLang === "vi"
        ? "Đang khởi tạo tiến trình tải & chia đoạn VAD…"
        : "Starting video download & VAD chunking…"
    );
    resetAudioEngine();
    try {
      const response = await fetch(`${HTTP}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          urls: [trimmed],
          referer: trimmed,
          source_language: sourceLang,
          target_language: targetLang,
          voice: effectiveVoice,
          translator_engine: engineMode,
          bgm_mode: bgmMode,
          asr_mode: defaultMode,
          download_video: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Could not create dub job");
      setJob(payload);
      setCurrentTime(0);
      setNotice(
        uiLang === "vi"
          ? `Đã tạo tác vụ #${payload.job_id} · Đang chuẩn bị đoạn đầu tiên…`
          : `Created job #${payload.job_id} · Preparing first chunk…`
      );
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Failed to start video dubbing");
    } finally {
      setBusy(false);
    }
  }, [
    bgmMode,
    defaultMode,
    effectiveVoice,
    engineMode,
    online,
    resetAudioEngine,
    sourceLang,
    targetLang,
    uiLang,
    urlInput,
  ]);

  const uploadLocalVideo = useCallback(
    async (file: File) => {
      if (!online) {
        setNotice(uiLang === "vi" ? "Backend đang offline." : "Backend is offline.");
        return;
      }
      setBusy(true);
      setNotice(
        uiLang === "vi"
          ? `Đang tải lên "${file.name}" (${(file.size / (1024 * 1024)).toFixed(1)} MB)…`
          : `Uploading "${file.name}" (${(file.size / (1024 * 1024)).toFixed(1)} MB)…`
      );
      resetAudioEngine();
      try {
        const response = await fetch(`${HTTP}/jobs/upload`, {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": encodeURIComponent(file.name),
            "X-Source-Language": sourceLang,
            "X-Target-Language": targetLang,
            "X-Voice": effectiveVoice,
            "X-Translator-Engine": engineMode,
            "X-Bgm-Mode": bgmMode,
            "X-Asr-Mode": defaultMode,
          },
          body: file,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Upload failed");
        setJob(payload);
        setCurrentTime(0);
        setNotice(
          uiLang === "vi"
            ? `Đã tải lên "${file.name}" · Đang tách giọng & thuyết minh…`
            : `Uploaded "${file.name}" · Extracting speech & dubbing…`
        );
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Video upload failed");
      } finally {
        setBusy(false);
      }
    },
    [bgmMode, defaultMode, effectiveVoice, engineMode, online, resetAudioEngine, sourceLang, targetLang, uiLang]
  );

  const attachActiveExtensionJob = useCallback(async () => {
    if (!online) {
      setNotice(uiLang === "vi" ? "Backend đang offline." : "Backend is offline.");
      return;
    }
    try {
      const response = await fetch(`${HTTP}/jobs/active`);
      const payload = await response.json();
      if (!payload.active || !payload.job_id) {
        setNotice(
          uiLang === "vi"
            ? "Chưa có tác vụ nào đang chạy từ Extension hoặc Web."
            : "No active job found from Extension or Web."
        );
        return;
      }
      if (jobRef.current?.job_id !== payload.job_id) {
        resetAudioEngine();
      }
      setJob(payload);
      setNotice(
        uiLang === "vi"
          ? `Đã đồng bộ tác vụ #${payload.job_id} (${payload.title || payload.url})`
          : `Synced job #${payload.job_id} (${payload.title || payload.url})`
      );
    } catch {
      setNotice(
        uiLang === "vi" ? "Không kiểm tra được tác vụ đang chạy." : "Could not fetch active jobs."
      );
    }
  }, [online, resetAudioEngine, uiLang]);

  const stopCurrentJob = useCallback(async () => {
    const activeId = jobRef.current?.job_id;
    if (!activeId) return;
    stopWebAudioNode();
    waitingForChunkRef.current = false;
    setWaitingChunkIndex(null);
    try {
      const res = await fetch(`${HTTP}/jobs/${activeId}/stop`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.job_id && data.chunks) {
          setJob(data);
        }
      }
      setNotice(uiLang === "vi" ? "Đã dừng tác vụ thuyết minh." : "Stopped dubbing job.");
    } catch {
      // Ignore stop error
    }
  }, [stopWebAudioNode, uiLang]);

  const openExtensionFolder = useCallback(async () => {
    setShowExtensionGuide(true);
    try {
      const res = await fetch(`${HTTP}/jobs/open-extension-folder`, { method: "POST" });
      if (res.ok) {
        setNotice(
          uiLang === "vi"
            ? "🧩 Đã mở trang chrome://extensions trên Cốc Cốc + mở thư mục Extension và copy sẵn đường dẫn vào Clipboard!"
            : "🧩 Opened chrome://extensions, File Explorer, and copied extension path to Clipboard!"
        );
      } else {
        setNotice(
          uiLang === "vi"
            ? "🧩 Đã hiển thị hướng dẫn cài Extension bên dưới (Đường dẫn: F:\\repo\\speak real time\\extension)."
            : "🧩 Displayed extension guide below."
        );
      }
    } catch {
      setNotice(
        uiLang === "vi"
          ? "🧩 Đã hiển thị hướng dẫn cài Extension bên dưới (Đường dẫn: F:\\repo\\speak real time\\extension)."
          : "🧩 Displayed extension guide below."
      );
    }
  }, [uiLang]);

  const injectExtensionToCocCoc = useCallback(async () => {
    if (!online) {
      setNotice(uiLang === "vi" ? "Backend đang offline." : "Backend is offline.");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${HTTP}/jobs/inject-extension`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlInput.trim() || jobRef.current?.url || undefined }),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.detail || "Inject failed");
      const count = payload.injected_count ?? 0;
      setNotice(
        uiLang === "vi"
          ? count > 0
            ? `⚡ Đã bật & nhấp nháy nút 「🇻🇳 VI · Thuyết minh」 (góc trên bên trái video) trên ${count} tab Cốc Cốc và đưa cửa sổ Cốc Cốc lên trước!`
            : "⚡ Đã kết nối Cốc Cốc! Hãy mở tab Douyin / TikTok / YouTube rồi bấm lại nút này."
          : `⚡ Injected & highlighted "🇻🇳 VI · Thuyết minh" button into ${count} Cốc Cốc video tab(s)!`
      );
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not inject extension into Cốc Cốc");
    } finally {
      setBusy(false);
    }
  }, [online, uiLang, urlInput]);

  const cleanupStorage = useCallback(async () => {
    if (!online) return;
    stopWebAudioNode();
    resetAudioEngine();
    setJob(null);
    try {
      const res = await fetch(`${HTTP}/jobs/cleanup?keep_active=false`, { method: "POST" });
      const data = await res.json();
      setNotice(
        uiLang === "vi"
          ? `🗑 Đã giải phóng RAM & xóa sạch ${data.removed_dirs ?? 0} bộ nhớ đệm tạm (.run/video_dub = ${data.remaining_bytes ?? 0} B).`
          : `🗑 Freed RAM and cleared ${data.removed_dirs ?? 0} temporary job caches.`
      );
    } catch {
      setNotice(uiLang === "vi" ? "Không xóa được bộ nhớ đệm." : "Failed to clean cache.");
    }
  }, [online, resetAudioEngine, stopWebAudioNode, uiLang]);

  const handleVideoSeeked = useCallback(() => {
    const video = videoRef.current;
    const activeJob = jobRef.current;
    if (!video || !activeJob) return;
    const t = video.currentTime;
    setCurrentTime(t);
    const chunk = activeJob.chunks.find((c) => t >= c.start && t < c.end);
    if (chunk && !chunk.ready) {
      const now = Date.now();
      if (lastSeekPostedRef.current.index !== chunk.i || now - lastSeekPostedRef.current.at > 1200) {
        lastSeekPostedRef.current = { index: chunk.i, at: now };
        void fetch(`${HTTP}/jobs/${activeJob.job_id}/seek`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ t }),
        }).catch(() => {});
      }
    }
    syncPlayback();
  }, [syncPlayback]);

  const seekToTime = useCallback(
    (timeSec: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.currentTime = Math.max(0, timeSec);
      handleVideoSeeked();
      if (video.paused) {
        void video.play().catch(() => {});
      }
    },
    [handleVideoSeeked]
  );

  const handleSubtitlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if ((event.target as HTMLElement).closest("button")) return;
      event.preventDefault();
      subDragRef.current = { startY: event.clientY, startBottom: subBottomPercent };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [subBottomPercent]
  );

  const handleSubtitlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!subDragRef.current) return;
    const parent = event.currentTarget.parentElement;
    const height = parent?.clientHeight || 400;
    const deltaY = subDragRef.current.startY - event.clientY;
    const nextBottom = Math.max(3, Math.min(78, subDragRef.current.startBottom + (deltaY / height) * 100));
    setSubBottomPercent(nextBottom);
  }, []);

  const handleSubtitlePointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!subDragRef.current) return;
    subDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const activeCue = job?.subs.find((cue) => currentTime >= cue.start && currentTime <= cue.end) || null;
  const readyCount = job ? job.chunks.filter((c) => c.ready).length : 0;
  const totalChunks = job ? job.chunks.length : 0;
  const storyBible = job?.bible;
  const hasStoryBible =
    Boolean(storyBible?.synopsis) ||
    Boolean(storyBible?.genre_tone) ||
    Boolean(storyBible?.characters?.length) ||
    Boolean(storyBible?.terms && Object.keys(storyBible.terms).length > 0);

  return (
    <section
      className="videoDubWorkspace"
      hidden={hidden}
      aria-label={uiLang === "vi" ? "Thuyết minh Video và TikTok" : "Video and TikTok Dubbing"}
    >
      {/* Top Control Bar */}
      <div className="videoDubControlCard">
        <div className="videoDubHeaderRow">
          <div className="videoDubIdentity">
            <span className="videoDubBadge">04</span>
            <div>
              <h2>
                {uiLang === "vi"
                  ? "THUYẾT MINH & PHỤ ĐỀ VIDEO / TIKTOK (CHUNKED STREAMING)"
                  : "REAL-TIME CHUNKED VIDEO / TIKTOK DUBBING & SUBS"}
              </h2>
              <small>
                {uiLang === "vi"
                  ? "Dán link TikTok, Douyin, YouTube, Bilibili, Coursera hoặc tải file video · Vừa xem vừa dịch & lồng tiếng từng đoạn như xem trực tiếp"
                  : "Paste TikTok, Douyin, YouTube, Bilibili, Coursera URL or upload video · Chunked VAD + ASR + Translation + VieNeu/Kokoro TTS"}
              </small>
            </div>
          </div>
          <div className="videoDubTopActions">
            <button
              type="button"
              className="videoDubSecondaryBtn"
              onClick={() => void injectExtensionToCocCoc()}
              disabled={busy || !online}
              title={
                uiLang === "vi"
                  ? "Kích hoạt ngay nút 『🇻🇳 VI · Thuyết minh』 trên các tab Douyin / TikTok / YouTube đang mở trong Cốc Cốc (không cần cài thủ công)"
                  : "Immediately inject the 🇻🇳 VI · Thuyết minh button into open Cốc Cốc tabs"
              }
            >
              ⚡ {uiLang === "vi" ? "Bật nút VI trên Cốc Cốc" : "Activate on Cốc Cốc"}
            </button>
            <button
              type="button"
              className="videoDubSecondaryBtn"
              onClick={() => void attachActiveExtensionJob()}
              title={
                uiLang === "vi"
                  ? "Đồng bộ với video đang được Extension trình duyệt dịch trên TikTok / YouTube"
                  : "Attach to active job triggered by the Browser Extension"
              }
            >
              🔗 {uiLang === "vi" ? "Đồng bộ Extension" : "Sync Extension"}
            </button>
            <button
              type="button"
              className="videoDubSecondaryBtn"
              onClick={() => void openExtensionFolder()}
              title={
                uiLang === "vi"
                  ? "Mở trang quản lý Extension trên Cốc Cốc, mở thư mục extension và hiện hướng dẫn"
                  : "Open chrome://extensions and extension folder"
              }
            >
              🧩 {uiLang === "vi" ? "Cài Extension Trình duyệt" : "Browser Extension"}
            </button>
            <button
              type="button"
              className="videoDubSecondaryBtn"
              onClick={() => void cleanupStorage()}
              disabled={busy || !online}
              title={
                uiLang === "vi"
                  ? "Giải phóng toàn bộ RAM và xóa sạch các file đệm tạm trong .run/video_dub"
                  : "Free RAM and delete all temporary job files"
              }
            >
              🗑 {uiLang === "vi" ? "Dọn RAM & Cache" : "Clear Cache"}
            </button>
          </div>
        </div>

        {/* URL & File Upload Row */}
        <div className="videoDubInputRow">
          <input
            type="url"
            className="videoDubUrlInput"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !busy) void startUrlJob();
            }}
            placeholder={
              uiLang === "vi"
                ? "Dán link video TikTok, Douyin, YouTube, Bilibili hoặc link .mp4 / .m3u8…"
                : "Paste TikTok, Douyin, YouTube, Bilibili or direct .mp4 / .m3u8 URL…"
            }
            disabled={busy}
          />
          <button
            type="button"
            className="videoDubPrimaryBtn"
            onClick={() => void startUrlJob()}
            disabled={busy || !online}
          >
            {busy ? "◌" : "▶"} <span>{uiLang === "vi" ? "Thuyết minh URL" : "Start Dubbing"}</span>
          </button>
          <label className={`videoDubUploadBtn ${busy || !online ? "disabled" : ""}`}>
            <input
              type="file"
              accept="video/*,audio/*,.mp4,.mkv,.webm,.mov,.mp3,.wav,.m4a"
              disabled={busy || !online}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void uploadLocalVideo(file);
                e.currentTarget.value = "";
              }}
            />
            <span>📁 {uiLang === "vi" ? "Chọn file Video/Audio" : "Upload Video/Audio"}</span>
          </label>
          {job && ["loading", "running"].includes(job.state) && (
            <button type="button" className="videoDubStopBtn" onClick={() => void stopCurrentJob()}>
              ■ {uiLang === "vi" ? "Dừng" : "Stop"}
            </button>
          )}
        </div>

        {/* Settings Row */}
        <div className="videoDubSettingsRow">
          <div className="compactLanguagePair">
            <select
              aria-label={uiLang === "vi" ? "Ngôn ngữ gốc video" : "Video source language"}
              value={sourceLang}
              onChange={(e) => setSourceLang(e.target.value)}
              disabled={busy}
            >
              <option value="auto">AUTO · {uiLang === "vi" ? "Tự nhận diện" : "Auto detect"}</option>
              {DUB_LANGUAGES.map(([code, vi, en]) => (
                <option key={code} value={code}>
                  {vi} · {en}
                </option>
              ))}
            </select>
            <b>→</b>
            <select
              aria-label={uiLang === "vi" ? "Ngôn ngữ thuyết minh" : "Target dubbing language"}
              value={targetLang}
              onChange={(e) => {
                const nextLang = e.target.value;
                setTargetLang(nextLang);
                setVoice(
                  nextLang === "vi"
                    ? "F1"
                    : nextLang === "zh"
                      ? "zm_yunxi"
                      : ["ja", "ko"].includes(nextLang)
                        ? "M1"
                        : "am_adam"
                );
              }}
              disabled={busy}
            >
              {DUB_LANGUAGES.map(([code, vi, en]) => (
                <option key={code} value={code}>
                  {vi} · {en}
                </option>
              ))}
            </select>
          </div>

          <label className="videoDubCompactField">
            <span>{uiLang === "vi" ? "Giọng đọc TTS" : "TTS Voice"}</span>
            <select
              value={effectiveVoice}
              onChange={(e) => setVoice(e.target.value)}
              disabled={busy || !(voiceOptions[targetLang]?.length)}
            >
              {(voiceOptions[targetLang] || []).map((opt) => (
                <option key={opt.id} value={opt.id} disabled={!opt.installed}>
                  {opt.label}
                  {opt.installed ? "" : uiLang === "vi" ? " · thiếu tệp" : " · missing"}
                </option>
              ))}
            </select>
          </label>

          <label className="videoDubCompactField">
            <span>{uiLang === "vi" ? "Bộ dịch" : "Translator"}</span>
            <select
              value={engineMode}
              onChange={(e) => setEngineMode(e.target.value as "local" | "llm")}
              disabled={busy}
            >
              <option value="local">Hy-MT2 7B (Local GPU)</option>
              <option value="llm">
                {uiLang === "vi"
                  ? "Advisor LLM + Story Bible (API)"
                  : "Advisor LLM + Story Bible (API)"}
              </option>
            </select>
          </label>

          <label className="videoDubCompactField">
            <span>{uiLang === "vi" ? "Nhạc nền (BGM)" : "BGM Mixing"}</span>
            <select
              value={bgmMode}
              onChange={(e) => setBgmMode(e.target.value as "mute" | "duck" | "demucs")}
              disabled={busy}
            >
              <option value="mute">
                {uiLang === "vi"
                  ? "Tắt hẳn tiếng gốc · Chỉ giọng thuyết minh (Khuyên dùng)"
                  : "Pure Dub Only · 0% Original Voice (Recommended)"}
              </option>
              <option value="demucs">
                {uiLang === "vi"
                  ? "Demucs AI GPU (Tách giọng nói gốc · Giữ nhạc nền BGM)"
                  : "Demucs AI GPU (Strip Vocals · Keep BGM)"}
              </option>
              <option value="duck">
                {uiLang === "vi"
                  ? "Trộn nền nhẹ 10% (Giữ âm thanh môi trường nhỏ)"
                  : "Light Ambient Ducking (10%)"}
              </option>
            </select>
          </label>

          <label className="videoDubSliderField">
            <span>
              {uiLang === "vi" ? "Âm lượng Thuyết minh" : "Dub Volume"}: {dubVolume}%
            </span>
            <input
              type="range"
              min={0}
              max={150}
              step={5}
              value={dubVolume}
              onChange={(e) => setDubVolume(Number(e.target.value))}
            />
          </label>

          <label className="videoDubSliderField">
            <span>
              {uiLang === "vi" ? "Tiếng gốc Video" : "Raw Video"}: {origVideoVolume}%
            </span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={origVideoVolume}
              onChange={(e) => setOrigVideoVolume(Number(e.target.value))}
            />
          </label>
        </div>

        {(notice || job?.stage) && (
          <div className="videoDubNoticeBar" role="status">
            <span>{notice ? `${notice}${job?.stage ? ` · (${job.stage})` : ""}` : job?.stage}</span>
            {job && (
              <small>
                Job #{job.job_id} · {job.state.toUpperCase()} · {readyCount}/{totalChunks}{" "}
                {uiLang === "vi" ? "đoạn hoàn tất" : "chunks ready"}
              </small>
            )}
          </div>
        )}

        {showExtensionGuide && (
          <div className="videoDubExtBanner">
            <div>
              <b>
                🧩{" "}
                {uiLang === "vi"
                  ? "Cách cài & sử dụng Extension xem trực tiếp trên Douyin / TikTok / YouTube / Bilibili:"
                  : "How to install & use Browser Extension on Douyin / TikTok / YouTube / Bilibili:"}
              </b>
              <ol>
                <li>
                  {uiLang === "vi"
                    ? "Cách 1 (Nhanh nhất trên Cốc Cốc): Mở video trên Cốc Cốc rồi bấm nút 「⚡ Bật nút VI trên Cốc Cốc」 ở góc trên bên phải màn hình này."
                    : "Option 1 (Instant on Cốc Cốc): Open the video tab in Cốc Cốc and click 「⚡ Activate on Cốc Cốc」 above."}
                </li>
                <li>
                  {uiLang === "vi"
                    ? "Cách 2 (Cài cố định vào trình duyệt): Hệ thống vừa tự mở trang "
                    : "Option 2 (Permanent install): Go to "}
                  <code>chrome://extensions</code>
                  {uiLang === "vi"
                    ? " (hoặc "
                    : " (or "}
                  <code>coccoc://extensions</code>
                  {uiLang === "vi"
                    ? ") và copy sẵn đường dẫn vào Clipboard → Bật Developer mode (Chế độ nhà phát triển) ở góc phải trên → Bấm Load unpacked (Tải tiện ích đã giải nén) → Nhấn Ctrl+V để dán "
                    : ") → Enable Developer mode → Click Load unpacked → Paste "}
                  <code>F:\repo\speak real time\extension</code>
                  {uiLang === "vi" ? " rồi bấm Select Folder." : " and click Select Folder."}
                </li>
                <li>
                  {uiLang === "vi"
                    ? "Cách dùng khi xem video: Mở bất kỳ video Douyin, TikTok, YouTube, Bilibili nào → Nhìn ở GÓC TRÊN BÊN TRÁI khung hình video sẽ có nút màu đỏ 「🇻🇳 VI · Thuyết minh」 → Bấm vào đó để tắt tiếng gốc, tự động dịch + đọc thuyết minh tiếng Việt và hiện phụ đề kéo thả ngay trên video!"
                    : "How to use: Open any video on Douyin, TikTok, YouTube, or Bilibili → Click the red 「🇻🇳 VI · Thuyết minh」 pill at the TOP-LEFT corner of the video player!"}
                </li>
              </ol>
            </div>
            <button type="button" onClick={() => setShowExtensionGuide(false)}>
              ×
            </button>
          </div>
        )}
      </div>

      {/* Main Two-Column Player + Transcript Layout */}
      <div className="videoDubMainGrid">
        {/* Left: Video Player + Chunk Progress Strip + Draggable Subtitle Overlay */}
        <div className="videoDubPlayerColumn">
          <div className="videoDubStageWrapper">
            {job && job.chunks.length > 0 && (
              <div
                className="videoDubChunkStrip"
                title={
                  uiLang === "vi"
                    ? "Thanh tiến độ từng đoạn (Xanh: Đã xong · Xám: Đang xử lý). Nhấp để tua tới đoạn đó."
                    : "Chunk readiness bar (Green: Ready · Gray: Pending). Click a segment to seek."
                }
              >
                {job.chunks.map((c) => {
                  const totalDur = Math.max(1, job.duration || c.end);
                  const widthPct = Math.max(0.8, ((c.end - c.start) / totalDur) * 100);
                  const isCurrent = currentTime >= c.start && currentTime < c.end;
                  const statusClass = c.ready ? "ready" : job.state === "running" && c.i === readyCount ? "running" : "pending";
                  return (
                    <button
                      key={c.i}
                      type="button"
                      className={`videoDubChunkSeg ${statusClass} ${isCurrent ? "current" : ""}`}
                      style={{ width: `${widthPct}%` }}
                      onClick={() => seekToTime(c.start)}
                      title={`#${c.i + 1} (${formatTime(c.start)}–${formatTime(c.end)}) · ${c.ready ? "READY" : "PENDING"}`}
                    />
                  );
                })}
              </div>
            )}

            <div className="videoDubVideoContainer">
              {job ? (
                <>
                  <video
                    ref={videoRef}
                    key={job.job_id}
                    src={job.has_video ? `${HTTP}/jobs/${job.job_id}/video` : undefined}
                    controls
                    playsInline
                    muted={origVideoVolume === 0}
                    onLoadedMetadata={(e) => {
                      const v = e.currentTarget;
                      const clamped = Math.max(0, Math.min(1, origVideoVolume / 100));
                      v.muted = clamped === 0;
                      v.volume = clamped;
                    }}
                    onPlay={() => {
                      ensureAudioContext();
                      syncPlayback();
                    }}
                    onPause={() => {
                      if (!waitingForChunkRef.current) stopWebAudioNode();
                    }}
                    onSeeked={handleVideoSeeked}
                    onRateChange={syncPlayback}
                    onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                  >
                    <track kind="captions" />
                  </video>
                  {!job.has_video && (
                    <div className="videoDubAudioOnlyNote">
                      <b>🎧 {job.title || "Audio Stream"}</b>
                      <p>
                        {uiLang === "vi"
                          ? "Tác vụ này đang phát trực tiếp trên tab trình duyệt (Extension) hoặc chỉ có luồng âm thanh."
                          : "This job is streaming directly in the browser tab (Extension) or is audio-only."}
                      </p>
                    </div>
                  )}

                  {waitingChunkIndex !== null && (
                    <div className="videoDubBufferingBadge">
                      <span>⏳</span>
                      <b>
                        {uiLang === "vi"
                          ? `Đang chờ dịch & lồng tiếng đoạn #${waitingChunkIndex + 1}… (Tự động phát tiếp khi xong)`
                          : `Waiting for chunk #${waitingChunkIndex + 1} dubbing… (Auto-resumes when ready)`}
                      </b>
                    </div>
                  )}

                  {activeCue && (
                    <div
                      className="videoDubFloatingSub"
                      style={{ bottom: `${subBottomPercent}%`, fontSize: `${subFontSize}px` }}
                      onPointerDown={handleSubtitlePointerDown}
                      onPointerMove={handleSubtitlePointerMove}
                      onPointerUp={handleSubtitlePointerUp}
                      onPointerCancel={handleSubtitlePointerUp}
                      title={uiLang === "vi" ? "Kéo để di chuyển vị trí phụ đề" : "Drag to reposition subtitles"}
                    >
                      <p className="videoDubSubTarget">{activeCue.vi}</p>
                      {showBilingualSubs && activeCue.zh && (
                        <p className="videoDubSubSource">{activeCue.zh}</p>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="videoDubPlaceholder">
                  <span>🎬</span>
                  <h3>
                    {uiLang === "vi"
                      ? "Sẵn sàng thuyết minh Video & TikTok"
                      : "Ready for Video & TikTok Dubbing"}
                  </h3>
                  <p>
                    {uiLang === "vi"
                      ? "Dán link TikTok / Douyin / YouTube / Bilibili ở trên, chọn file từ máy, hoặc mở video trên trình duyệt Cốc Cốc / Chrome với Extension."
                      : "Paste a TikTok / Douyin / YouTube / Bilibili URL above, upload a local file, or trigger from the Browser Extension."}
                  </p>
                </div>
              )}
            </div>

            {/* Subtitle Style & Export Footer Bar */}
            <div className="videoDubStageFooter">
              <div className="videoDubSubControls">
                <label className="compactToggle">
                  <input
                    type="checkbox"
                    checked={showBilingualSubs}
                    onChange={(e) => setShowBilingualSubs(e.target.checked)}
                  />
                  <span>{uiLang === "vi" ? "Phụ đề song ngữ" : "Bilingual subs"}</span>
                </label>
                <div className="videoDubFontBtns">
                  <button
                    type="button"
                    onClick={() => setSubFontSize((s) => Math.max(14, s - 2))}
                    title={uiLang === "vi" ? "Giảm cỡ chữ phụ đề" : "Decrease subtitle size"}
                  >
                    A-
                  </button>
                  <span>{subFontSize}px</span>
                  <button
                    type="button"
                    onClick={() => setSubFontSize((s) => Math.min(40, s + 2))}
                    title={uiLang === "vi" ? "Tăng cỡ chữ phụ đề" : "Increase subtitle size"}
                  >
                    A+
                  </button>
                </div>
              </div>

              {job && (
                <div className="videoDubExportBtns">
                  <a
                    className={`videoDubDownloadLink ${job.subs.length === 0 ? "disabled" : ""}`}
                    href={`${HTTP}/jobs/${job.job_id}/subs.srt`}
                    download={`${job.title || job.job_id}.srt`}
                  >
                    ⬇ {uiLang === "vi" ? "Tải Phụ đề (.SRT)" : "Download .SRT"}
                  </a>
                  <a
                    className={`videoDubDownloadLink primary ${readyCount === 0 ? "disabled" : ""}`}
                    href={`${HTTP}/jobs/${job.job_id}/export`}
                    download
                  >
                    ⬇{" "}
                    {uiLang === "vi"
                      ? `Xuất Video Thuyết minh (${readyCount}/${totalChunks})`
                      : `Export Dubbed Video (${readyCount}/${totalChunks})`}
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Chunk Matrix, Story Bible, and Bilingual Subtitle List */}
        <div className="videoDubSideColumn">
          <div className="videoDubCard">
            <header className="videoDubCardHeader">
              <div>
                <b>{uiLang === "vi" ? "TIẾN ĐỘ CHIA ĐOẠN (CHUNKS)" : "CHUNK PIPELINE"}</b>
                <small>
                  {job
                    ? `${job.title || job.url} · ${formatTime(job.duration)}`
                    : uiLang === "vi"
                      ? "Chưa có video"
                      : "No active video"}
                </small>
              </div>
              {job && (
                <span className={`videoDubStatusPill ${job.state}`}>
                  {job.state.toUpperCase()} · {readyCount}/{totalChunks}
                </span>
              )}
            </header>

            {job && job.error && <p className="videoDubErrorText">⚠ {job.error}</p>}

            {job && job.chunks.length > 0 ? (
              <div className="videoDubChunkPills">
                {job.chunks.map((c) => {
                  const isCurrent = currentTime >= c.start && currentTime < c.end;
                  const statusClass = c.ready ? "ready" : job.state === "running" && c.i === readyCount ? "running" : "pending";
                  return (
                    <button
                      key={c.i}
                      type="button"
                      className={`videoDubChunkPill ${statusClass} ${isCurrent ? "current" : ""}`}
                      onClick={() => seekToTime(c.start)}
                      title={`${formatTime(c.start)} - ${formatTime(c.end)}`}
                    >
                      <b>#{c.i + 1}</b>
                      <small>{formatTime(c.start)}</small>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="videoDubMutedText">
                {uiLang === "vi"
                  ? "Video sẽ được chia thành các đoạn 8–16 giây theo khoảng lặng giọng nói (Silero VAD). Đoạn đầu tiên chỉ mất vài giây để bắt đầu phát."
                  : "Videos are split into 8–16s speech-aware chunks via Silero VAD. Playback begins as soon as Chunk #1 is ready."}
              </p>
            )}

            {hasStoryBible && (
              <details className="videoDubStoryBible" open>
                <summary>
                  📖 {uiLang === "vi" ? "Story Bible & Ngữ cảnh Video" : "Story Bible & Context"}
                </summary>
                <div className="videoDubBibleBody">
                  {storyBible?.synopsis && <p>{storyBible.synopsis}</p>}
                  {storyBible?.genre_tone && (
                    <small className="videoDubToneTag">{storyBible.genre_tone}</small>
                  )}
                  {storyBible?.terms && Object.keys(storyBible.terms).length > 0 && (
                    <div className="videoDubTermTags">
                      {Object.entries(storyBible.terms).map(([src, tgt]) => (
                        <span key={src}>
                          {src} → <b>{tgt}</b>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </details>
            )}
          </div>

          {/* Interactive Bilingual Transcript */}
          <div className="videoDubCard videoDubSubListCard">
            <header className="videoDubCardHeader">
              <b>
                {uiLang === "vi"
                  ? `PHỤ ĐỀ SONG NGỮ (${job?.subs.length || 0} CÂU)`
                  : `BILINGUAL SUBTITLES (${job?.subs.length || 0} CUES)`}
              </b>
              <small>
                {uiLang === "vi" ? "Nhấp vào câu bất kỳ để tua video" : "Click any cue to seek"}
              </small>
            </header>

            <div className="videoDubSubFeed">
              {!job || job.subs.length === 0 ? (
                <div className="compactEmpty">
                  <span>💬</span>
                  <p>
                    {job && ["loading", "running"].includes(job.state)
                      ? uiLang === "vi"
                        ? "Đang nhận dạng giọng nói và dịch đoạn đầu tiên…"
                        : "Transcribing and translating the first chunk…"
                      : uiLang === "vi"
                        ? "Danh sách phụ đề song ngữ theo mốc thời gian sẽ xuất hiện tại đây"
                        : "Time-synced bilingual subtitles will appear here"}
                  </p>
                </div>
              ) : (
                job.subs.map((cue, idx) => {
                  const active = currentTime >= cue.start && currentTime <= cue.end;
                  return (
                    <button
                      type="button"
                      key={`${cue.start}-${idx}`}
                      className={`videoDubCueItem ${active ? "active" : ""}`}
                      onClick={() => seekToTime(cue.start)}
                    >
                      <time>
                        {formatTime(cue.start)}
                        <br />
                        <small>{formatTime(cue.end)}</small>
                      </time>
                      <div className="videoDubCueText">
                        <p className="cueTarget">{cue.vi}</p>
                        {cue.zh && <p className="cueSource">{cue.zh}</p>}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
