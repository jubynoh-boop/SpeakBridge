from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from desktop.speech_output import find_output, output_test_wav, play_wav


class SpeechOutputTests(unittest.TestCase):
    def audio(self):
        audio = MagicMock()
        audio.get_host_api_info_by_type.return_value = {"index": 3, "defaultOutputDevice": 0}
        devices = [
            {"index": 0, "name": "CABLE Input", "hostApi": 3, "maxOutputChannels": 2, "defaultSampleRate": 48000},
            {"index": 1, "name": "Headphones", "hostApi": 3, "maxOutputChannels": 2, "defaultSampleRate": 48000},
        ]
        audio.get_device_count.return_value = len(devices)
        audio.get_device_info_by_index.side_effect = lambda index: devices[index]
        return audio

    def test_selected_headphones_override_default_cable_and_resample(self):
        audio = self.audio()
        with patch("pyaudiowpatch.PyAudio", return_value=audio):
            self.assertEqual(play_wav(output_test_wav(), "Headphones"), "Headphones")
        kwargs = audio.open.call_args.kwargs
        self.assertEqual((kwargs["output_device_index"], kwargs["rate"], kwargs["channels"]), (1, 48000, 2))
        blocks = [call.args[0] for call in audio.open.return_value.write.call_args_list]
        self.assertGreater(len(b"".join(blocks)), len(output_test_wav()))
        audio.open.return_value.close.assert_called_once()
        audio.terminate.assert_called_once()

    def test_missing_device_reports_error_without_default_fallback(self):
        audio = self.audio()
        with patch("pyaudiowpatch.PyAudio", return_value=audio):
            with self.assertRaisesRegex(RuntimeError, "Không tìm thấy"):
                play_wav(output_test_wav(), "Disconnected headphones")
        audio.open.assert_not_called()
        audio.terminate.assert_called_once()

    def test_cancelled_playback_does_not_open_stream(self):
        audio = self.audio()
        with patch("pyaudiowpatch.PyAudio", return_value=audio):
            play_wav(output_test_wav(), "Headphones", cancelled=lambda: True)
        audio.open.assert_not_called()
        audio.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
