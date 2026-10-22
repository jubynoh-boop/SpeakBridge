# SpeakBridge V2

Ứng dụng phiên dịch cuộc họp hai chiều chạy local trên Windows:

- **Tôi nói:** chọn ngôn ngữ microphone và ngôn ngữ đích; Anh/Trung dùng Kokoro, Nhật/Hàn dùng Supertonic 3 để phát giọng local qua VB-CABLE.
- **Bên kia nói:** chọn hoặc tự nhận diện ngôn ngữ Discord/Zoom/YouTube → phụ đề theo ngôn ngữ đích.

Âm thanh và nội dung cuộc họp được xử lý trên PC.

## Kiến trúc

```text
Microphone → Silero VAD → Faster-Whisper → Hy-MT2 7B → bản dịch → Kokoro Anh/Trung hoặc Supertonic Nhật/Hàn → CABLE Input
Âm thanh hệ thống → WASAPI loopback → Silero VAD → Faster-Whisper → Hy-MT2 7B → phụ đề đã chọn
```

| Thành phần | Công dụng | Tài nguyên chính | Dung lượng local hiện tại |
|---|---|---|---|
| Silero VAD | Phát hiện lúc bắt đầu/kết thúc nói, loại im lặng | CPU, rất nhẹ | nằm trong Python environment |
| Faster-Whisper | Âm thanh → transcript và phát hiện ngôn ngữ | GPU; CPU phụ cho audio | Turbo ~3.02 GB, Large-v3 ~5.76 GB |
| Hy-MT2 7B Q6 | Dịch transcript giữa các ngôn ngữ | GPU/Vulkan, dùng VRAM nhiều nhất | ~5.74 GB |
| Kokoro-82M | Đọc bản dịch Anh/Trung thành giọng nói | GPU; có thể chạy CPU nhưng chậm hơn | ~0.61 GB |
| Supertonic 3 | Đọc bản dịch Nhật/Hàn | CPU, không thêm VRAM | ~0.4 GB tải vào `.model-cache` trên ổ cài app |
| WASAPI | Thu âm thanh đang phát từ Meet/Discord/YouTube | CPU, rất nhẹ | có sẵn trong Windows |

- **FAST:** `large-v3-turbo`, beam 1, ưu tiên độ trễ thấp và dùng ít VRAM hơn.
- **QUALITY:** `large-v3`, beam 5, ưu tiên độ chính xác.
- VAD giữ pre-roll và chờ khoảng 760 ms im lặng để hạn chế mất phụ âm đầu hoặc cắt từ quá sớm.
- Ngữ cảnh cuộc họp và Hotwords được đưa vào bước nhận dạng/dịch.
- Một Whisper worker và một Hy-MT2 server được dùng chung cho hai luồng để phù hợp GPU 16 GB.
- Nhật/Hàn trong 02A/02B là chế độ mở rộng, chưa được kiểm thử rộng trên audio họp thực tế. Nên chọn đúng ngôn ngữ đầu vào thay vì AUTO. Mục 03 dùng PP-OCRv6 cho tiếng Nhật, PP-OCRv5 ONNX CPU cho tiếng Hàn.

## Chạy bằng cách nhấp đúp

- Chỉ mở `SPEAKBRIDGE.bat`: chọn **1** để cài lần đầu, **2** để cài VB-CABLE nếu cần.
- Những lần sau: chọn **3** để khởi động.
- Dừng tiến trình của bản cài này: chọn **4**.
- Chuẩn bị/tải lại model: chọn **5**. Mục **6/7** dành cho nhà phát triển.

Giao diện mở tại `http://localhost:3000/`.

## Thiết lập Discord / Zoom

### Routing đúng, không dịch vòng

1. SpeakBridge **Microphone**: microphone thật, ví dụ `USB Condenser Microphone`.
2. SpeakBridge **Đầu ra giọng dịch**: `CABLE Input (VB-Audio Virtual Cable)`.
3. Discord/Zoom/Meet **Microphone**: `CABLE Output (VB-Audio Virtual Cable)`.
4. Discord/Zoom/Meet **Speaker**: tai nghe thật, ví dụ `Headphones (High Definition Audio Device)`.
5. SpeakBridge **Thiết bị đang phát bên kia**: cùng tai nghe thật ở bước 4.

Không dùng `CABLE In 16ch` cho loa cuộc họp. Nó không phải endpoint cần thiết của routing một cable này.

### Để dịch lời người bên kia thành phụ đề Việt

1. Cho Discord/Zoom phát ra tai nghe hoặc loa bạn đang dùng.
2. Trong SpeakBridge, mục **Thiết bị đang phát Discord / YouTube**, chọn đúng tai nghe/loa đó; có thể để mặc định Windows.
3. Bấm **Bắt đầu nghe bên kia**.
4. Bản gốc và phụ đề Việt xuất hiện trong bảng **02A**; luồng này không có TTS.

Hai nút **Tôi nói** và **Nghe bên kia** hoạt động độc lập và có thể bật cùng lúc.

## Ngôn ngữ, lịch sử và giao diện

- Hai bảng 02A/02B có dropdown ngôn ngữ nguồn và đích độc lập.
- AUTO được nhận diện lại ở mỗi đoạn; khi biết chắc bên kia nói tiếng Trung, khóa nguồn thành **Tiếng Trung** sẽ ổn định hơn.
- UI chỉ hiện **Việt, Anh và Trung** vì đây là ba ngôn ngữ đã được kiểm thử end-to-end. Whisper/Hy-MT2 hỗ trợ rộng hơn nhưng sẽ chỉ được mở thêm sau khi có audio benchmark và kiểm thử từng cặp.
- TTS local hiện phát giọng cho tiếng Anh và tiếng Trung.
- Mỗi bảng có **Xuất .doc** và **Xóa lịch sử**.
- Lịch sử chỉ nằm trong RAM, tối đa 100 đoạn mỗi bảng; tải lại trang là xóa và không làm ổ đĩa tăng dần.
- Nút **Cài đặt / Settings** đổi toàn bộ giao diện giữa tiếng Việt và English; model dịch mặc định là Hy-MT2 7B.

## Voice Typing toàn Windows

SpeakBridge chạy một helper nhỏ ở khay hệ thống. Đặt con trỏ vào Discord,
Chrome, Word hoặc ứng dụng có ô nhập; giữ `Ctrl+Alt+Space` để nói và thả ra
để nhận dạng. Settings cho phép chọn:

- Nhập nguyên văn tiếng Việt/Anh/Trung.
- Dịch Việt/Anh/Trung trước khi nhập.
- Nhấp ô phím tắt rồi bấm tổ hợp mới; không cần gõ tên phím bằng tay.
- Chọn riêng microphone WASAPI cho Voice Typing; nên chọn USB Condenser, không chọn CABLE Output.
- Với chữ đã gõ trong ô chat: bôi đen đoạn cần dịch hoặc chỉ đặt con trỏ trong ô để dịch toàn bộ, sau đó bấm `F8`. SpeakBridge thay chữ bằng bản dịch và không tự nhấn Enter.
- Để nghe đọc chữ: dùng chuột **bôi đen chữ có thể sao chép trước**, sau đó bấm và thả `Ctrl+Alt+R`. Trong **Cài đặt → Đọc chữ đã bôi đen**, chọn đọc nguyên văn hoặc dịch rồi đọc, ngôn ngữ chữ và ngôn ngữ giọng đọc; có thể đổi phím tắt. App không chụp màn hình, không hiện khung khoanh vùng OCR và không tự chọn toàn bộ trang nếu bạn chưa bôi đen. Chữ nằm trong ảnh/video vẫn cần mục 03 OCR riêng. Chọn loa/tai nghe riêng cho giọng đọc trong Cài đặt; đầu phát này độc lập với VB-CABLE của 02B.
- Đổi tổ hợp phím push-to-talk; helper tự nạp lại sau khi lưu.

Trong **Cài đặt → Kiểm tra helper / phím tắt**, dấu ✓ xác nhận Windows đã đăng ký phím tắt; dấu ⚠ cho biết phím bị ứng dụng khác chiếm hoặc cấu hình không hợp lệ. Đổi sang tổ hợp khác (ví dụ `Ctrl+Shift+F9` để đọc chữ) rồi lưu; helper tự cập nhật trong khoảng 2 giây. Chỉ mở trang web không đồng nghĩa helper Windows đang hoạt động.

Để chọn nơi nghe giọng đọc, vào **Cài đặt → Đọc chữ đã bôi đen → Loa / tai nghe đọc chữ**, chọn tai nghe/loa thật, bấm **Thử âm thanh**, rồi **Lưu cấu hình hotkey**. Thiết bị này độc lập với đầu ra VB-CABLE của 02B. Nếu thiết bị bị ngắt kết nối, app báo lỗi để bạn chọn lại.

Overlay luôn nổi và icon khay đổi màu theo trạng thái: đỏ khi đang nghe, cam
khi nhận dạng/dịch và xanh khi hoàn tất. Âm chime nhẹ phát lúc bắt đầu, thả
phím, thành công hoặc lỗi; app không gửi thông báo toast Windows. Helper lưu
control đang có con trỏ và dùng WM_PASTE cho
ô nhập chuẩn, hoặc Win32 Ctrl+V cho Chrome/Discord/Electron.

Helper chỉ dán văn bản và không tự nhấn Enter. Nó dùng lại Whisper và Hy-MT2
đang chạy nên không tải thêm model. Có thể tạo file EXE bằng
`powershell -ExecutionPolicy Bypass -File desktop/build-hotkey.ps1`; kết quả nằm trong `desktop/dist` và không được commit.

## Ngữ cảnh và từ hay nhận sai

Trong **Ngữ cảnh cuộc họp**, mô tả chủ đề bằng câu đầy đủ, ví dụ:

```text
Cuộc họp về thanh toán thương mại điện tử, hóa đơn, hoàn tiền và chuyển khoản.
```

Trong **Hotwords / Glossary**, nhập mỗi dòng một thuật ngữ hoặc tên riêng:

```text
thanh toán
phương thức thanh toán
Tên sản phẩm
Tên khách hàng
```

Nói một câu đầy đủ như “Tôi muốn thanh toán hóa đơn này” sẽ chính xác hơn chỉ nói riêng từ “thanh toán”.

Hai trường này hoạt động thật trong backend:

- **Ngữ cảnh** được gửi cho Hy-MT2 khi dịch và được thêm vào gợi ý nhận dạng của Whisper. Chỉ nên viết 1–3 câu mô tả chủ đề; không dán cả tài liệu dài.
- **Glossary** được đưa vào hotwords của Whisper và dùng để khôi phục đúng cách viết tên riêng/thuật ngữ sau nhận dạng. Mỗi dòng chỉ nên chứa một tên hoặc cụm từ.

## Trợ lý AI gợi ý trả lời

Bảng giữa 02A và 02B có thể đọc câu khách vừa nói, lịch sử cuộc họp gần nhất và các đoạn liên quan trong tài liệu bạn tải lên để gợi ý câu trả lời. Có thể kích hoạt sau mỗi câu hoặc sau 0,5–20 giây im lặng, bật/tắt gợi ý deal mềm và khóa AI chỉ được tư vấn trong phạm vi tài liệu.

1. Vào **Cài đặt → AI gợi ý trả lời**.
2. Chọn OpenAI API, Claude, DeepSeek, **9Router** hoặc Custom OpenAI-compatible.
3. Với 9Router, mặc định dùng `http://127.0.0.1:20128/v1` và model/alias `auto`.
4. Nhập API key, bấm **Lưu trợ lý**, rồi **Kiểm tra API**.
5. Ở bảng giữa, tải tài liệu dưới loại **Kiến thức dịch vụ** hoặc **Log cuộc họp**, bật trợ lý và chọn thời gian kích hoạt.

Phần tìm đoạn tài liệu phù hợp chạy local. Khi tạo câu trả lời, app chỉ gửi câu khách nói, context gần nhất và các đoạn tài liệu đã tìm được tới API bạn chọn. API key nằm trong `config/advisor.local.json`, tài liệu nằm trong `.advisor-data/`; cả hai đều bị Git bỏ qua. OpenAI API có key/billing riêng và không dùng quota Codex/ChatGPT.

Hỗ trợ DOCX, DOC dạng text/HTML, TXT, MD, CSV, JSON và HTML. File `.doc` nhị phân cũ cần Save As thành `.docx`.

## Vị trí model — không dùng ổ C

Copy `config/models.example.json` thành `config/models.local.json`, rồi sửa đường dẫn. File local bị Git bỏ qua. Máy hiện tại dùng:

```json
{
  "hf_home": "models/huggingface",
  "torch_home": ".model-cache/torch",
  "pip_cache": ".model-cache/pip",
  "npm_cache": ".model-cache/npm",
  "runtime_temp": ".model-cache/temp",
  "hy_mt2_model": "models/HY-MT2-7B-Q6_K.gguf"
}
```

Settings trong app hiển thị trạng thái cài đặt, dung lượng và đường dẫn thật của từng model. Không có nút “tải model theo ngôn ngữ” vì Whisper và Hy-MT2 là model đa ngôn ngữ; tải lặp sẽ chỉ tốn thêm dung lượng mà không cải thiện pipeline.

## Cài đặt thủ công

Yêu cầu: Windows 11, NVIDIA driver mới, Python 3.11, Node.js 22+ và VB-CABLE. Chọn mục **5** trong `SPEAKBRIDGE.bat` để tải file Hy-MT2 chính thức vào đường dẫn đã cấu hình.

Giọng Việt/Nhật/Hàn dùng Supertonic chạy CPU: tổng hợp 8 bước và chèn khoảng nghỉ 120 ms giữa đoạn. Tiếng Việt giữ tối đa 450 ký tự ngữ cảnh mỗi đoạn và đọc tốc độ 1,08x; mức 1,12x trước đó làm bài thử lặp cụm từ kém hơn. Thời gian tạo âm thanh khác với thời gian đọc hết đoạn; tăng chất lượng tổng hợp cũng tốn thời gian hơn. Log backend ghi riêng hai số này, không ghi nội dung đã chọn. Bản dịch vượt giới hạn token sẽ bị báo lỗi, không được đọc như bản hoàn chỉnh. Phát âm tên riêng và từ trộn nhiều ngôn ngữ vẫn có thể chưa tốt; không cắt tiếng thở bằng noise gate vì có thể làm mất âm tiết nhỏ.

Giọng Việt có engine tùy chọn **VieNeu v3 Turbo 3.8.3**: chạy CPU trong `runtime/vieneu/.venv`, không thay thư viện Python chính hoặc nạp thêm model GPU. Cài bằng `powershell -ExecutionPolicy Bypass -File scripts/prepare-vieneu.ps1`; model nằm trong `models/vieneu-v3-turbo` trên ổ cài app. Bật bằng file `config/speech.local.json` với `{"vietnamese_engine":"vieneu"}` rồi khởi động lại backend. M1/F1 đã lưu tương ứng Hải Đăng/Trúc Ly; dropdown hiện tên thật. Anh/Trung/Nhật/Hàn không đổi. Đặt lại `supertonic` để quay về engine cũ. Bài thử câu bị cà lăm và hai câu thanh toán không phát hiện lặp từ trong 10 lượt nhận dạng lại; đây là kiểm tra chẩn đoán, không bảo đảm mọi câu đều phát âm đúng. Câu mẫu tạo âm thanh khoảng 1,2 giây khi model đã nạp; lần đầu cần thêm thời gian nạp.

API key trợ lý được bảo vệ bằng Windows DPAPI theo tài khoản đang dùng. Không đưa cấu hình riêng hoặc thư mục backup lên GitHub; chuyển sang tài khoản Windows khác cần nhập lại API key.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
.\prepare-models.ps1
.\start.ps1
```

Lần tải model đầu tiên cần Internet. Sau đó app có thể chạy offline.

## Lưu ý

- Đây là clause streaming: app chốt và dịch theo cụm lời nói, chưa phải simultaneous decoding từng token.
- FAST phù hợp họp thường ngày; QUALITY tốn thêm VRAM và khởi động lâu hơn.
- Không chạy đồng thời một bản Whisper/Hy-MT2 khác ở repo kia vì có thể vượt 16 GB VRAM.
- Model không được commit lên GitHub. Mã nguồn SpeakBridge dùng Apache-2.0; model Hy-MT2 và Kokoro dùng Apache-2.0, Silero VAD dùng MIT.
- Xem [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) để biết giấy phép của model và thư viện AI bên thứ ba.
