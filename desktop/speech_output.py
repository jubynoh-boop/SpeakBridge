"""Device-specific WAV playback shared by the helper and its output test."""
from __future__ import annotations

import audioop
import io
import logging
import math
import struct
import threading
import wave
from functools import wraps
from typing import Callable


AUDIO_API_LOCK = threading.RLock()


def serialized_audio_api(function):
    @wraps(function)
    def locked(*args, **kwargs):
        # PortAudio initialization/termination is not thread-safe. The settings
        # page can request input/output enumeration and a playback test together.
        with AUDIO_API_LOCK:
            return function(*args, **kwargs)
    return locked


def find_output(audio, requested: str):
    host = audio.get_host_api_info_by_type(13)  # WASAPI
    if requested == "__default__":
        return audio.get_device_info_by_index(int(host["defaultOutputDevice"]))
    for index in range(audio.get_device_count()):
        device = audio.get_device_info_by_index(index)
        if (device["hostApi"] == host["index"] and device.get("maxOutputChannels", 0) > 0
                and not device.get("isLoopbackDevice", False)
                and str(device["name"]).casefold() == requested.casefold()):
            return device
    raise RuntimeError(f"Không tìm thấy loa/tai nghe: {requested}. Hãy chọn lại thiết bị phát.")


@serialized_audio_api
def play_wav(audio_data: bytes, output_device: str = "__default__", cancelled: Callable[[], bool] = lambda: False) -> str:
    import pyaudiowpatch as pyaudio

    with wave.open(io.BytesIO(audio_data), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() not in (1, 2):
            raise ValueError("Speech audio must be mono/stereo PCM16 WAV")
        channels, sample_rate = source.getnchannels(), source.getframerate()
        pcm = source.readframes(source.getnframes())
    audio = pyaudio.PyAudio()
    stream = None
    try:
        device = find_output(audio, output_device)
        target_rate = int(device["defaultSampleRate"])
        target_channels = min(2, int(device["maxOutputChannels"]))
        if channels != target_channels:
            pcm = audioop.tostereo(pcm, 2, 1, 1) if target_channels == 2 else audioop.tomono(pcm, 2, 0.5, 0.5)
            channels = target_channels
        if sample_rate != target_rate:
            pcm, _ = audioop.ratecv(pcm, 2, channels, sample_rate, target_rate, None)
        if cancelled():
            return str(device["name"])
        stream = audio.open(format=pyaudio.paInt16, channels=channels, rate=target_rate,
                            output=True, output_device_index=int(device["index"]), frames_per_buffer=1024)
        logging.info("Read-aloud output: %s (%s Hz, %s channels)", device["name"], target_rate, channels)
        block_size = 1024 * channels * 2
        for offset in range(0, len(pcm), block_size):
            if cancelled():
                break
            stream.write(pcm[offset:offset + block_size])
        return str(device["name"])
    finally:
        try:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            audio.terminate()


def output_test_wav() -> bytes:
    rate = 24_000
    samples = []
    for frequency in (660, 880):
        count = int(rate * 0.18)
        for index in range(count):
            envelope = math.sin(math.pi * index / count) ** 2
            samples.append(int(32767 * 0.2 * envelope * math.sin(2 * math.pi * frequency * index / rate)))
        samples.extend([0] * int(rate * 0.04))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()
