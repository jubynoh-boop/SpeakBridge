from __future__ import annotations

import base64
import html
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from backend.local_secrets import protect_key, unprotect_key


PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "gpt-6-luna"),
    "anthropic": ("https://api.anthropic.com/v1", ""),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "9router": ("http://127.0.0.1:20128/v1", "auto"),
    "custom": ("http://127.0.0.1:11434/v1", ""),
}
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".doc", ".docx"}


def _spaces(value: str) -> str:
    return re.sub(r"[\t \u00a0]+", " ", re.sub(r"\r\n?", "\n", value)).strip()


def _strip_markup(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)</?(?:p|div|tr|li|h[1-6]|br)[^>]*>", "\n", value)
    return _spaces(html.unescape(re.sub(r"(?s)<[^>]+>", " ", value)))


def extract_text(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ DOCX, DOC (HTML), TXT, MD, CSV, JSON và HTML")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("File DOCX không hợp lệ") from exc
        xml = re.sub(r"</w:p>|</w:tr>", "\n", xml)
        xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
        return _strip_markup(xml)
    decoded = ""
    for encoding in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if suffix in {".html", ".htm", ".doc"}:
        if suffix == ".doc" and "<" not in decoded[:1000]:
            printable = sum(character.isprintable() or character.isspace() for character in decoded)
            if printable / max(1, len(decoded)) < 0.8:
                raise ValueError("DOC nhị phân cũ chưa hỗ trợ; hãy Save As DOCX")
        decoded = _strip_markup(decoded)
    return _spaces(decoded)


def _chunks(text: str, target: int = 900, overlap: int = 140) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}|(?<=[.!?。！？])\s+", text) if part.strip()]
    output: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[index:index + target] for index in range(0, len(paragraph), target - overlap)] if len(paragraph) > target * 2 else [paragraph]
        for piece in pieces:
            candidate = f"{current}\n{piece}".strip()
            if current and len(candidate) > target:
                output.append(current)
                current = f"{current[-overlap:]} {piece}".strip()
            else:
                current = candidate
    if current:
        output.append(current)
    return output[:1000]


def _tokens(text: str) -> Counter[str]:
    normalized = text.casefold()
    words = re.findall(r"[^\W_]{2,}", normalized, flags=re.UNICODE)
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    return Counter(words + [chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))])


class AdvisorEngine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.documents_dir = root / ".advisor-data" / "documents"
        self.config_path = root / "config" / "advisor.local.json"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        # Migrate old local plaintext configuration without changing its options.
        # The backup remains private and must not be uploaded with a release.
        if self.config_path.exists():
            try:
                existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing = {}
            if isinstance(existing, dict) and existing.get("api_key"):
                self._write_config(existing)

    def _write_config(self, config: dict[str, Any]) -> None:
        saved = dict(config)
        key = str(saved.pop("api_key", ""))
        unreadable = str(saved.pop("_unreadable_api_key", ""))
        saved.pop("api_key_error", None)
        saved["api_key_dpapi"] = protect_key(key) if key else unreadable
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.config_path)

    def config(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "enabled": False, "provider": "9router", "base_url": PROVIDERS["9router"][0],
            "model": PROVIDERS["9router"][1], "api_key": "", "strict_scope": True,
            "deal_mode": True, "trigger_mode": "silence", "silence_seconds": 3.0, "max_suggestions": 3,
            "knowledge_context": "",
        }
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                result.update(loaded)
        except (OSError, ValueError):
            pass
        encrypted = str(result.pop("api_key_dpapi", ""))
        if encrypted:
            try:
                result["api_key"] = unprotect_key(encrypted)
            except (ValueError, UnicodeError):
                # A copied configuration must not make the settings page fail
                # or prevent entering a replacement key on another account.
                result["api_key"] = ""
                result["_unreadable_api_key"] = encrypted
                result["api_key_error"] = "API key belongs to another Windows user or is damaged; enter it again."
        return result

    def public_config(self) -> dict[str, Any]:
        result = self.config()
        result.pop("_unreadable_api_key", None)
        key = str(result.pop("api_key", ""))
        result.update(has_api_key=bool(key.strip()), api_key_hint=(f"••••{key[-4:]}" if key else ""))
        return result

    def save_config(self, incoming: dict[str, Any]) -> dict[str, Any]:
        current = self.config()
        provider = str(incoming.get("provider", current["provider"])).lower().strip()
        if provider not in PROVIDERS:
            raise ValueError("Nhà cung cấp API không được hỗ trợ")
        base_url = str(incoming.get("base_url", "")).strip() or PROVIDERS[provider][0]
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Base URL API không hợp lệ")
        model = str(incoming.get("model", "")).strip() or PROVIDERS[provider][1]
        if not model:
            raise ValueError("Hãy nhập model/alias chính xác")
        new_key = str(incoming.get("api_key", "")).strip()
        if new_key:
            current["api_key"] = new_key
            current.pop("_unreadable_api_key", None)
            current.pop("api_key_error", None)
        elif incoming.get("clear_api_key"):
            current["api_key"] = ""
            current.pop("_unreadable_api_key", None)
            current.pop("api_key_error", None)
        current.update({
            "enabled": bool(incoming.get("enabled", False)), "provider": provider,
            "base_url": base_url.rstrip("/"), "model": model,
            "strict_scope": bool(incoming.get("strict_scope", True)),
            "deal_mode": bool(incoming.get("deal_mode", True)),
            "trigger_mode": "sentence" if incoming.get("trigger_mode") == "sentence" else "silence",
            "silence_seconds": max(0.5, min(20.0, float(incoming.get("silence_seconds", 3.0)))),
            "max_suggestions": max(1, min(5, int(incoming.get("max_suggestions", 3)))),
            "knowledge_context": str(incoming.get("knowledge_context", current.get("knowledge_context", ""))).strip()[:12000],
        })
        self._write_config(current)
        return self.public_config()

    def add_document(self, filename: str, encoded: str, category: str) -> dict[str, Any]:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Dữ liệu file không hợp lệ") from exc
        if not raw or len(raw) > 12_000_000:
            raise ValueError("File phải nhỏ hơn 12 MB")
        text = extract_text(Path(filename).name, raw)[:1_000_000]
        if len(text) < 20:
            raise ValueError("Tài liệu không có đủ nội dung văn bản")
        document_id = uuid.uuid4().hex
        chunk_data = _chunks(text)
        metadata = {
            "id": document_id, "name": Path(filename).name[:180],
            "category": category if category in {"knowledge", "meeting_log"} else "knowledge",
            "created_at": datetime.now(timezone.utc).isoformat(), "characters": len(text), "chunks": len(chunk_data),
        }
        (self.documents_dir / f"{document_id}.json").write_text(
            json.dumps({**metadata, "text": text, "chunks_data": chunk_data}, ensure_ascii=False), encoding="utf-8"
        )
        return metadata

    def documents(self) -> list[dict[str, Any]]:
        output = []
        for path in self.documents_dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                output.append({key: item[key] for key in ("id", "name", "category", "created_at", "characters", "chunks")})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(output, key=lambda item: item["created_at"], reverse=True)

    def delete_document(self, document_id: str) -> bool:
        if not re.fullmatch(r"[a-f0-9]{32}", document_id):
            return False
        path = self.documents_dir / f"{document_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    def retrieve(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        results = []
        for path in self.documents_dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for index, chunk in enumerate(item.get("chunks_data", [])):
                chunk_tokens = _tokens(str(chunk))
                overlap = sum(min(count, chunk_tokens.get(token, 0)) for token, count in query_tokens.items())
                if overlap:
                    coverage = overlap / max(1, sum(query_tokens.values()))
                    density = overlap / math.sqrt(max(1, sum(chunk_tokens.values())))
                    results.append({
                        "document": item.get("name", path.stem), "category": item.get("category", "knowledge"),
                        "chunk": index + 1, "text": str(chunk), "score": round(coverage * .78 + density * .22, 4),
                    })
        return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]

    @staticmethod
    def _post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"), {"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Không kết nối được API: {exc.reason}") from exc

    def _complete(self, system: str, user: str) -> str:
        config = self.config()
        key, provider = str(config.get("api_key", "")).strip(), str(config["provider"])
        if not key:
            raise RuntimeError("Chưa cấu hình API key cho trợ lý")
        base_url, model = str(config["base_url"]).rstrip("/"), str(config["model"])
        if provider == "anthropic":
            result = self._post(f"{base_url}/messages", {
                "model": model, "max_tokens": 700, "temperature": .2, "system": system,
                "messages": [{"role": "user", "content": user}],
            }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return "\n".join(str(item.get("text", "")) for item in result.get("content", []) if item.get("type") == "text").strip()
        result = self._post(f"{base_url}/chat/completions", {
            "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": .2, "max_tokens": 700, "stream": False,
        }, {"Authorization": f"Bearer {key}"})
        try:
            return str(result["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("API trả về định dạng không nhận diện được") from exc

    @staticmethod
    def _parse(raw: str, maximum: int, sources: list[dict[str, Any]]) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise RuntimeError("AI không trả về JSON hợp lệ")
        try:
            payload = json.loads(match.group(0))
        except ValueError as exc:
            raise RuntimeError("AI trả về JSON bị lỗi") from exc
        allowed = {item["document"] for item in sources}
        suggestions = []
        for item in payload.get("suggestions", [])[:maximum]:
            if isinstance(item, dict) and str(item.get("answer", "")).strip():
                suggestions.append({
                    "title": str(item.get("title", "Gợi ý"))[:100], "answer": str(item["answer"])[:1800],
                    "reason": str(item.get("reason", ""))[:400],
                    "sources": [str(value) for value in item.get("sources", []) if str(value) in allowed],
                    "confidence": max(0.0, min(1.0, float(item.get("confidence", .5)))),
                })
        return {"suggestions": suggestions, "follow_up_question": str(payload.get("follow_up_question", ""))[:500]}

    def suggest(self, customer_text: str, customer_original: str, history: list[dict[str, str]], meeting_context: str, knowledge_context_override: str = "") -> dict[str, Any]:
        config = self.config()
        if not config.get("enabled"):
            raise RuntimeError("Chế độ gợi ý đang tắt")
        history = history[-16:]
        history_text = "\n".join(f"{item.get('speaker', 'unknown')}: {item.get('text', '')}" for item in history)
        knowledge_context = (knowledge_context_override or str(config.get("knowledge_context", ""))).strip()[:12000]
        sources = self.retrieve(f"{customer_text}\n{customer_original}\n{history_text[-5000:]}")
        if knowledge_context:
            sources.insert(0, {
                "document": "Context tư vấn nhập tay", "category": "knowledge_context", "chunk": 1,
                "text": knowledge_context, "score": 1.0,
            })
            sources = sources[:7]
        if config.get("strict_scope") and not sources:
            return {"ok": True, "suggestions": [], "follow_up_question": "", "notice": "Không tìm thấy dữ liệu phù hợp trong tài liệu đã cung cấp.", "sources": []}
        source_text = "\n\n".join(f"[SOURCE: {item['document']} | đoạn {item['chunk']}]\n{item['text']}" for item in sources) or "(Không có tài liệu liên quan)"
        scope = "Chỉ dùng SOURCE cho mọi thông tin thực tế về sản phẩm, giá và cam kết; thiếu dữ liệu thì nói cần kiểm tra hoặc hỏi làm rõ." if config.get("strict_scope") else "Ưu tiên SOURCE và tuyệt đối không bịa giá, tính năng hoặc cam kết."
        deal = "Áp dụng deal mềm: xác nhận nhu cầu, nêu giá trị, xử lý phản đối và đề xuất bước tiếp theo; không gây áp lực." if config.get("deal_mode") else "Trả lời trung tính, trực tiếp, không chủ động bán hàng."
        system = (
            f"Bạn là trợ lý cuộc họp cho người tư vấn. {scope} {deal} Không nhắc mình là AI. Trả lời tiếng Việt. "
            "Xuất DUY NHẤT JSON: "
            '{"suggestions":[{"title":"...","answer":"...","reason":"...","sources":["ten-file"],"confidence":0.0}],"follow_up_question":"..."}'
        )
        user = (
            f"Bối cảnh cuộc họp:\n{meeting_context or '(không có)'}\n\nLịch sử khách và tư vấn viên:\n{history_text or '(chưa có)'}\n\n"
            f"Khách nói nguyên bản:\n{customer_original}\n\nBản dịch:\n{customer_text}\n\nSOURCE:\n{source_text}\n\n"
            f"Tạo tối đa {config['max_suggestions']} câu người dùng có thể nói ngay."
        )
        parsed = self._parse(self._complete(system, user), int(config["max_suggestions"]), sources)
        return {
            "ok": True, **parsed, "notice": "", "sources": sources,
            "provider": config["provider"], "model": config["model"],
            "inputs": {
                "history_items": len(history), "retrieved_sources": len(sources),
                "knowledge_context_chars": len(knowledge_context), "meeting_context_chars": len(meeting_context),
            },
        }

    def test_provider(self) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        reply = self._complete("Chỉ trả lời một từ OK", "Kiểm tra kết nối. Chỉ trả lời OK.")
        return {"ok": True, "reply": reply[:80], "latency_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000)}
