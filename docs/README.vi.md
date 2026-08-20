# SpeakBridge V2

Ứng dụng phiên dịch cuộc họp hai chiều chạy local trên Windows:

- **Tôi nói:** chọn ngôn ngữ microphone và ngôn ngữ đích; Anh/Trung có giọng đọc local qua VB-CABLE.
- **Bên kia nói:** chọn hoặc tự nhận diện ngôn ngữ Discord/Zoom/YouTube → phụ đề theo ngôn ngữ đích.

Âm thanh và nội dung cuộc họp được xử lý trên PC.

## Kiến trúc

```text
Microphone → Silero VAD → Faster-Whisper → Hy-MT2 7B → bản dịch → Kokoro Anh/Trung → CABLE Input
Âm thanh hệ thống → WASAPI loopback → Silero VAD → Faster-Whisper → Hy-MT2 7B → phụ đề đã chọn
```

| Thành phần | Công dụng | Tài nguyên chính | Dung lượng local hiện tại |
|---|---|---|---|
| Silero VAD | Phát hiện lúc bắt đầu/kết thúc nói, loại im lặng | CPU, rất nhẹ | nằm trong Python environment |
| Faster-Whisper | Âm thanh → transcript và phát hiện ngôn ngữ | GPU; CPU phụ cho audio | Turbo ~3.02 GB, Large-v3 ~5.76 GB |
| Hy-MT2 7B Q6 | Dịch transcript giữa các ngôn ngữ | GPU/Vulkan, dùng VRAM nhiều nhất | ~5.74 GB |
| Kokoro-82M | Đọc bản dịch Anh/Trung thành giọng nói | GPU; có thể chạy CPU nhưng chậm hơn | ~0.61 GB |
| WASAPI | Thu âm thanh đang phát từ Meet/Discord/YouTube | CPU, rất nhẹ | có sẵn trong Windows |

- **FAST:** `large-v3-turbo`, beam 1, ưu tiên độ trễ thấp và dùng ít VRAM hơn.
- **QUALITY:** `large-v3`, beam 5, ưu tiên độ chính xác.
- VAD giữ pre-roll và chờ khoảng 760 ms im lặng để hạn chế mất phụ âm đầu hoặc cắt từ quá sớm.
- Ngữ cảnh cuộc họp và Hotwords được đưa vào bước nhận dạng/dịch.
- Một Whisper worker và một Hy-MT2 server được dùng chung cho hai luồng để phù hợp GPU 16 GB.

## Chạy bằng cách nhấp đúp

Chỉ cần nhấp đúp `SPEAKBRIDGE.bat` và chọn trong một menu chung:

- Lần đầu chọn **1** để cài SpeakBridge.
- Chọn **2** để tải và mở bộ cài VB-CABLE chính thức. Xác nhận quyền Administrator và khởi động lại Windows sau khi cài. VB-CABLE là sản phẩm Donationware riêng của VB-Audio và không được đóng gói sẵn trong SpeakBridge.
- Những lần sau chọn **3** để khởi động hoặc **4** để dừng.
- Chọn **5** khi cần chuẩn bị/tải lại model.
- Mục **6–7** chỉ hiện trong Git working copy, dành cho nhà phát triển build helper và bản release; bản phát hành cho người dùng sẽ ẩn hai mục này.

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
- Đổi tổ hợp phím push-to-talk; helper tự nạp lại sau khi lưu.

Overlay luôn nổi và icon khay đổi màu theo trạng thái: đỏ khi đang nghe, cam
khi nhận dạng/dịch và xanh khi hoàn tất. Âm chime nhẹ phát lúc bắt đầu, thả
phím, thành công hoặc lỗi; app không gửi thông báo toast Windows. Helper lưu
control đang có con trỏ và dùng WM_PASTE cho
ô nhập chuẩn, hoặc Win32 Ctrl+V cho Chrome/Discord/Electron.

Helper chỉ dán văn bản và không tự nhấn Enter. Nó dùng lại Whisper và Hy-MT2
đang chạy nên không tải thêm model. Có thể tạo file EXE bằng mục **6** trong
`SPEAKBRIDGE.bat`; kết quả nằm trong `desktop/dist` và không được commit.

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

## Vị trí model — không dùng ổ C

Copy `config/models.example.json` thành `config/models.local.json`, rồi sửa đường dẫn. File local bị Git bỏ qua. Máy hiện tại dùng:

```json
{
  "hf_home": "F:/AI-Cache/huggingface-v2",
  "torch_home": "F:/AI-Cache/torch",
  "pip_cache": "F:/AI-Cache/pip",
  "npm_cache": "F:/AI-Cache/npm",
  "runtime_temp": "F:/AI-Cache/temp",
  "hy_mt2_model": "models/HY-MT2-7B-Q6_K.gguf"
}
```

Settings trong app hiển thị trạng thái cài đặt, dung lượng và đường dẫn thật của từng model. Không có nút “tải model theo ngôn ngữ” vì Whisper và Hy-MT2 là model đa ngôn ngữ; tải lặp sẽ chỉ tốn thêm dung lượng mà không cải thiện pipeline.

## Cài đặt thủ công

Yêu cầu: Windows 11, NVIDIA driver mới, Python 3.11, Node.js 22+ và VB-CABLE. Mục **5** trong `SPEAKBRIDGE.bat` tự tải file Hy-MT2 chính thức vào đường dẫn đã cấu hình.

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
