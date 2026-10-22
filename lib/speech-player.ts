export type SpeechAudio = Pick<HTMLAudioElement, "duration" | "onended" | "onpause" | "onerror" | "onloadedmetadata" | "play" | "pause"> & {ended?: boolean; setSinkId?: (id: string) => Promise<void>};
type Job = { url: string; sink: string; resolve: () => void; reject: (error: Error) => void };
type Run = { controller: AbortController; audio?: SpeechAudio };
const cancelled = () => new DOMException("Playback stopped", "AbortError");

export class SpeechPlayer {
  private queue: Job[] = [];
  private run: Run | null = null;
  private factory: (url: string) => SpeechAudio;
  private onStart: (audio: SpeechAudio, url: string) => (() => void);
  constructor(factory: (url: string) => SpeechAudio, onStart: (audio: SpeechAudio, url: string) => (() => void) = () => () => {}) {
    this.factory = factory; this.onStart = onStart;
  }
  enqueue(url: string, sink: string): Promise<void> {
    const pending = new Promise<void>((resolve, reject) => this.queue.push({url, sink, resolve, reject}));
    if (!this.run) {
      const run = { controller: new AbortController() };
      this.run = run;
      void this.pump(run);
    }
    return pending;
  }
  stop() {
    const run = this.run;
    this.run = null; // A new session must not wait for the cancelled session.
    for (const job of this.queue.splice(0)) job.reject(cancelled());
    run?.controller.abort();
    run?.audio?.pause();
  }
  private async pump(run: Run) {
    try {
      while (!run.controller.signal.aborted && this.queue.length) {
        const job = this.queue.shift()!;
        try { await this.play(job, run); job.resolve(); }
        catch (error) { job.reject(error instanceof Error ? error : new Error(String(error))); }
      }
    } finally { if (this.run === run) this.run = null; }
  }
  private async play(job: Job, run: Run) {
    const signal = run.controller.signal;
    const audio = this.factory(job.url); run.audio = audio;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cleanup = () => {};
    let abort = () => {};
    try {
      await new Promise<void>((resolve, reject) => {
        const fail = (error: Error) => reject(error);
        abort = () => fail(cancelled());
        signal.addEventListener("abort", abort, {once:true});
        const deadline = () => {
          if (timer) clearTimeout(timer);
          timer = setTimeout(() => fail(new Error("Audio playback timed out; check the selected output device")),
            Number.isFinite(audio.duration) && audio.duration > 0 ? Math.min(180000, audio.duration * 1000 + 10000) : 30000);
        };
        audio.onended = () => resolve();
        // Chromium dispatches pause before ended at the natural end of a clip.
        audio.onpause = () => { if (!audio.ended) fail(signal.aborted ? cancelled() : new Error("Audio playback was paused")); };
        audio.onerror = () => fail(new Error("Unable to play translated audio"));
        audio.onloadedmetadata = deadline;
        deadline();
        void (async () => {
          try {
            if (signal.aborted) throw cancelled();
            if (job.sink !== "default") {
              if (!audio.setSinkId) throw new Error("Browser cannot select audio output. Use Chrome / Edge.");
              await audio.setSinkId(job.sink);
            }
            if (signal.aborted) throw cancelled();
            cleanup = this.onStart(audio, job.url);
            await audio.play();
          } catch (error) { fail(error instanceof Error ? error : new Error(String(error))); }
        })();
      });
    } finally {
      if (timer) clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      audio.onended = null; audio.onpause = null; audio.onerror = null; audio.onloadedmetadata = null;
      audio.pause(); cleanup();
      if (run.audio === audio) run.audio = undefined;
    }
  }
}
