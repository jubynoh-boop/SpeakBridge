from __future__ import annotations

import queue
import threading
from typing import Any

import numpy as np


def list_input_devices() -> list[str]:
    """List physical/virtual recording devices available to the hotkey helper."""
    import pyaudiowpatch as pyaudio

    audio = pyaudio.PyAudio()
    try:
        wasapi_index = None
        for index in range(audio.get_host_api_count()):
            host = audio.get_host_api_info_by_index(index)
            if "WASAPI" in str(host["name"]):
                wasapi_index = int(host["index"])
                break
        names: list[str] = []
        for index in range(audio.get_device_count()):
            device = audio.get_device_info_by_index(index)
            if (
                device.get("maxInputChannels", 0) <= 0
                or device.get("isLoopbackDevice", False)
                or (wasapi_index is not None and int(device["hostApi"]) != wasapi_index)
            ):
                continue
            name = str(device["name"])
            if name not in names:
                names.append(name)
        return names
    finally:
        audio.terminate()


def list_output_devices() -> list[str]:
    """List real WASAPI playback devices that can be captured by loopback."""
    import pyaudiowpatch as pyaudio

    audio = pyaudio.PyAudio()
    try:
        wasapi_index = None
        for index in range(audio.get_host_api_count()):
            info = audio.get_host_api_info_by_index(index)
            if "WASAPI" in info["name"]:
                wasapi_index = info["index"]
                break
        if wasapi_index is None:
            return []

        names: list[str] = []
        for index in range(audio.get_device_count()):
            device = audio.get_device_info_by_index(index)
            if (
                device["hostApi"] == wasapi_index
                and device["maxOutputChannels"] > 0
                and not device.get("isLoopbackDevice", False)
            ):
                name = str(device["name"])
                if name not in names:
                    names.append(name)
        return names
    finally:
        audio.terminate()


class SystemAudioCapture:
    """Capture one Windows playback device through WASAPI loopback."""

    def __init__(self, device_name: str | None = None, sample_rate: int = 16_000) -> None:
        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio
        self._audio = pyaudio.PyAudio()
        self._device_name = device_name or None
        self.sample_rate = sample_rate
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)
        self._stream: Any | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.active_device = ""

    def _wasapi_info(self) -> dict[str, Any]:
        for index in range(self._audio.get_host_api_count()):
            info = self._audio.get_host_api_info_by_index(index)
            if "WASAPI" in info["name"]:
                return info
        raise RuntimeError("Windows WASAPI không khả dụng")

    def _find_loopback_device(self) -> dict[str, Any]:
        wasapi = self._wasapi_info()
        default_output = self._audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
        target = self._device_name or str(default_output["name"])

        loopbacks = []
        for index in range(self._audio.get_device_count()):
            device = self._audio.get_device_info_by_index(index)
            if device["hostApi"] == wasapi["index"] and device.get("isLoopbackDevice", False):
                loopbacks.append(device)
                if target.casefold() in str(device["name"]).casefold():
                    return device
        if self._device_name:
            raise RuntimeError(f"Không tìm thấy WASAPI loopback cho: {self._device_name}")
        if loopbacks:
            return loopbacks[0]
        raise RuntimeError("Không tìm thấy thiết bị WASAPI loopback")

    def _resample_mono(self, data: bytes, channels: int, native_rate: int) -> np.ndarray:
        audio = np.frombuffer(data, dtype=np.float32)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        if native_rate == self.sample_rate:
            return np.asarray(audio, dtype=np.float32)

        ratio = self.sample_rate / native_rate
        output_size = max(1, int(len(audio) * ratio))
        positions = np.arange(output_size, dtype=np.float64) / ratio
        positions = np.clip(positions, 0, len(audio) - 1)
        left = positions.astype(np.int64)
        right = np.minimum(left + 1, len(audio) - 1)
        mix = (positions - left).astype(np.float32)
        return np.asarray(audio[left] * (1 - mix) + audio[right] * mix, dtype=np.float32)

    def start(self) -> None:
        device = self._find_loopback_device()
        channels = int(device["maxInputChannels"])
        native_rate = int(device["defaultSampleRate"])
        native_chunk = max(1, round(native_rate * 0.032))
        self.active_device = str(device["name"])
        self._stream = self._audio.open(
            format=self._pyaudio.paFloat32,
            channels=channels,
            rate=native_rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=native_chunk,
        )
        self._running = True

        def read_loop() -> None:
            while self._running:
                try:
                    data = self._stream.read(native_chunk, exception_on_overflow=False)
                    chunk = self._resample_mono(data, channels, native_rate)
                    try:
                        self.audio_queue.put_nowait(chunk)
                    except queue.Full:
                        self.audio_queue.get_nowait()
                        self.audio_queue.put_nowait(chunk)
                except Exception:
                    if self._running:
                        self._running = False
                    break

        self._thread = threading.Thread(target=read_loop, daemon=True, name="wasapi-loopback")
        self._thread.start()

    def get_audio(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._audio.terminate()
