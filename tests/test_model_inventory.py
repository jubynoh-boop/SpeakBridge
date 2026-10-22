import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.model_inventory import inventory
from backend import server
from fastapi import HTTPException


class InventoryTests(unittest.TestCase):
    def test_default_huggingface_path_is_inside_models(self):
        with tempfile.TemporaryDirectory() as folder, patch("backend.model_inventory.Path.cwd", return_value=Path(folder)), patch.dict("os.environ", {}, clear=True):
            cache, assets = inventory()
            self.assertEqual(cache, Path(folder) / "models" / "huggingface")
            for asset in assets:
                self.assertTrue(Path(asset["path"]).is_relative_to(Path(folder)))

    def test_empty_directory_is_not_installed(self):
        with tempfile.TemporaryDirectory() as folder, patch("backend.model_inventory.Path.cwd", return_value=Path(folder)), patch.dict("os.environ", {"HF_HOME": folder, "HF_HUB_CACHE": folder, "SPEAKBRIDGE_HY_MODEL": str(Path(folder) / "hy.gguf")}):
            (Path(folder) / "models--Systran--faster-whisper-large-v3").mkdir()
            _, assets = inventory()
            whisper = next(item for item in assets if item["name"] == "Whisper large-v3")
            self.assertFalse(whisper["installed"])
            self.assertIn("model.bin", whisper["missing_files"])
            hy = next(item for item in assets if item["name"] == "Hy-MT2 7B Q6")
            self.assertFalse(hy["installed"])
            Path(hy["path"]).write_bytes(b"model")
            self.assertTrue(next(item for item in inventory()[1] if item["name"] == hy["name"])["installed"])

    def test_arbitrary_folder_open_is_rejected(self):
        with patch("backend.model_inventory.inventory", return_value=(Path("F:/models"), [])):
            with self.assertRaises(HTTPException) as error:
                server.open_model_folder({"name": "C:/Windows"})
            self.assertEqual(error.exception.status_code, 400)
