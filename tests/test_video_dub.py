import unittest
import numpy as np
from fastapi.testclient import TestClient

from backend.video_dub import (
    DemucsSeparator,
    DubSettings,
    Seg,
    VideoTranslator,
    mix_chunk,
    normalize_page_url,
    plan_chunks,
)
from backend import server


class FakeModels:
    def _wait_for_llm(self) -> None:
        return None

    def _translate_screen_lines(self, lines: list[str], source_lang: str, target_lang: str) -> list[str]:
        return [f"[{target_lang}] {line}" for line in lines]


class FakeAdvisor:
    def config(self) -> dict:
        return {}


class VideoDubTests(unittest.TestCase):
    def test_normalize_page_url(self) -> None:
        raw = "https://www.douyin.com/user/self?from_tab_name=main&modal_id=7694650962384489707&showTab=like"
        self.assertEqual(normalize_page_url(raw), "https://www.douyin.com/video/7694650962384489707")
        note = "https://www.douyin.com/note/7694650962384489707"
        self.assertEqual(normalize_page_url(note), "https://www.douyin.com/video/7694650962384489707")

    def test_plan_chunks_splits_contiguous_ranges(self) -> None:
        settings = DubSettings()
        speech = [(0.5, 4.2), (4.8, 11.5), (13.0, 22.0), (23.5, 31.0)]
        chunks = plan_chunks(32.0, speech, settings)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertAlmostEqual(chunks[0].start, 0.0)
        self.assertAlmostEqual(chunks[-1].end, 32.0)
        for idx in range(len(chunks) - 1):
            self.assertAlmostEqual(chunks[idx].end, chunks[idx + 1].start)

    def test_mute_mode_eliminates_original_audio_leak(self) -> None:
        settings = DubSettings()
        sep = DemucsSeparator(settings)
        raw_voice = np.ones((settings.mix_sr, 2), dtype=np.float32) * 0.8
        bgm, used_demucs = sep.bgm(raw_voice, 0.0, 1.0, mode="mute")
        self.assertFalse(used_demucs)
        self.assertEqual(float(np.max(np.abs(bgm))), 0.0)

    def test_mix_chunk_ducking_and_voice_overlay(self) -> None:
        settings = DubSettings()
        sr = settings.mix_sr
        duration = 2.0
        bgm = np.full((int(sr * duration), 2), 0.25, dtype=np.float32)
        tone = np.sin(np.linspace(0, 2 * np.pi * 440, int(sr * 0.8), dtype=np.float32)) * 0.5
        mixed = mix_chunk(bgm, [(0.2, tone)], settings, used_demucs=False)
        self.assertEqual(mixed.shape, (int(sr * duration), 2))
        self.assertLessEqual(float(np.max(np.abs(mixed))), 1.0)
        self.assertNotAlmostEqual(
            float(np.mean(np.abs(mixed[int(0.3 * sr) : int(0.7 * sr)]))),
            0.25,
            places=2,
        )

    def test_local_translator_batch(self) -> None:
        settings = DubSettings()
        translator = VideoTranslator(
            settings,
            FakeModels(),
            FakeAdvisor(),
            source_language="zh",
            target_language="vi",
            engine_mode="local",
        )
        segs = [Seg(start=0.0, end=1.5, zh="你好"), Seg(start=1.5, end=3.0, zh="世界")]
        translator.translate(segs, [1.5, 1.5], "zh")
        self.assertTrue(segs[0].vi.startswith("[vi] 你好"))
        self.assertTrue(segs[1].vi.startswith("[vi] 世界"))

    def test_jobs_endpoints_and_extension_cors(self) -> None:
        client = TestClient(server.app)
        res = client.get("/jobs/active", headers={"Origin": "https://www.tiktok.com"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(res.headers.get("access-control-allow-private-network"), "true")
        body = res.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("active", body)

        cleanup = client.post("/jobs/cleanup?keep_active=true")
        self.assertEqual(cleanup.status_code, 200)
        self.assertTrue(cleanup.json().get("ok"))

        opt = client.options(
            "/jobs",
            headers={
                "Origin": "https://www.douyin.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        self.assertEqual(opt.status_code, 204)
        self.assertEqual(opt.headers.get("access-control-allow-origin"), "*")
        self.assertEqual(opt.headers.get("access-control-allow-private-network"), "true")


if __name__ == "__main__":
    unittest.main()
