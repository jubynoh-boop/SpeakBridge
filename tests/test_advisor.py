import base64
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from backend.advisor import AdvisorEngine, extract_text


class AdvisorEngineTests(unittest.TestCase):
    def test_9router_is_default_and_key_is_never_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            engine = AdvisorEngine(Path(folder))
            saved = engine.save_config({
                "enabled": True,
                "provider": "9router",
                "base_url": "http://127.0.0.1:20128/v1",
                "model": "auto",
                "api_key": "secret-example-key",
            })
            self.assertEqual(saved["provider"], "9router")
            self.assertTrue(saved["has_api_key"])
            self.assertNotIn("api_key", saved)
            raw = json.loads((Path(folder) / "config" / "advisor.local.json").read_text(encoding="utf-8"))
            self.assertNotIn("api_key", raw)
            self.assertNotIn("secret-example-key", engine.config_path.read_text(encoding="utf-8"))
            self.assertTrue(raw["api_key_dpapi"])
            self.assertEqual(engine.config()["api_key"], "secret-example-key")

    def test_legacy_key_migrates_without_changing_provider(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config" / "advisor.local.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"api_key": "legacy-secret", "model": "custom-alias", "enabled": True}), encoding="utf-8")
            engine = AdvisorEngine(Path(folder))
            self.assertEqual(engine.config()["api_key"], "legacy-secret")
            self.assertEqual(engine.config()["model"], "custom-alias")
            self.assertTrue(engine.config()["enabled"])
            self.assertNotIn("legacy-secret", path.read_text())
            engine.save_config({"model": "custom-alias", "clear_api_key": True})
            self.assertFalse(engine.public_config()["has_api_key"])

    def test_document_upload_retrieval_and_strict_scope(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            engine = AdvisorEngine(Path(folder))
            content = "Gói ExampleSuite Pro hỗ trợ quản lý nội dung. Giá dịch vụ là 2.500 USD mỗi năm."
            document = engine.add_document(
                "service.txt",
                base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "knowledge",
            )
            self.assertEqual(document["name"], "service.txt")
            self.assertEqual(engine.retrieve("ExampleSuite giá dịch vụ")[0]["document"], "service.txt")
            engine.save_config({
                "enabled": True,
                "provider": "9router",
                "base_url": "http://127.0.0.1:20128/v1",
                "model": "auto",
                "strict_scope": True,
            })
            result = engine.suggest("Khách hỏi về một sản phẩm hoàn toàn khác", "unrelated product", [], "")
            self.assertEqual(result["suggestions"], [])
            self.assertIn("Không tìm thấy", result["notice"])

    def test_unreadable_key_can_be_replaced_without_exposing_ciphertext(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config" / "advisor.local.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"api_key_dpapi": "not-a-valid-blob", "model": "auto"}), encoding="utf-8")
            engine = AdvisorEngine(Path(folder))
            public = engine.public_config()
            self.assertFalse(public["has_api_key"])
            self.assertIn("api_key_error", public)
            self.assertNotIn("_unreadable_api_key", public)
            self.assertNotIn("api_key_dpapi", public)
            engine.save_config({"model": "auto"})
            self.assertEqual(json.loads(path.read_text())["api_key_dpapi"], "not-a-valid-blob")
            engine.save_config({"api_key": "replacement-secret", "model": "auto"})
            self.assertTrue(engine.public_config()["has_api_key"])
            self.assertNotIn("api_key_error", engine.public_config())

    def test_typed_service_context_is_injected_as_a_grounded_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            engine = AdvisorEngine(Path(folder))
            engine.save_config({
                "enabled": True,
                "provider": "9router",
                "base_url": "http://127.0.0.1:20128/v1",
                "model": "auto",
                "api_key": "test-key",
                "strict_scope": True,
            })
            engine._complete = lambda _system, _user: json.dumps({
                "suggestions": [{
                    "title": "Trả lời",
                    "answer": "Gói Pro có giá 2.500 USD mỗi năm.",
                    "reason": "Theo hồ sơ dịch vụ",
                    "sources": ["Context tư vấn nhập tay"],
                    "confidence": 0.9,
                }],
                "follow_up_question": "Anh/chị muốn dùng cho bao nhiêu người?",
            }, ensure_ascii=False)
            result = engine.suggest(
                "Khách hỏi giá gói Pro", "What is the Pro price?",
                [{"speaker": "customer", "text": "Tôi cần báo giá"}],
                "Cuộc họp tư vấn bán hàng",
                "Gói Pro có giá 2.500 USD mỗi năm.",
            )
            self.assertEqual(result["suggestions"][0]["sources"], ["Context tư vấn nhập tay"])
            self.assertEqual(result["inputs"]["history_items"], 1)
            self.assertGreater(result["inputs"]["knowledge_context_chars"], 0)

    def test_docx_extraction(self) -> None:
        memory = BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Thông tin dịch vụ ExampleSuite</w:t></w:r></w:p></w:body></w:document>',
            )
        self.assertIn("Thông tin dịch vụ ExampleSuite", extract_text("knowledge.docx", memory.getvalue()))


if __name__ == "__main__":
    unittest.main()
