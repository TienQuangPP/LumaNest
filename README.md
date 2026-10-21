<p align="center"><img src="fsmart/static/lumanest.svg" width="82" alt="LumaNest"></p>
<h1 align="center">LumaNest</h1>
<p align="center"><b>AI Photo Studio · Ảnh của bạn, không gian sáng tạo của bạn.</b></p>

Thư viện ảnh AI chạy trên máy: tổ chức nhiều bộ ảnh, tìm người bằng khuôn mặt, tìm nội dung bằng tiếng Việt và biến ảnh thành tác phẩm nghệ thuật. Backend **FastAPI + PyTorch + SQLite**, giao diện tiếng Việt; **OpenVINO** tăng tốc preset trên CPU.

## Mở ứng dụng trên Windows

1. Tải `LumaNest-1.0.1-windows-x64.zip` trong **Releases**, giải nén toàn bộ vào thư mục bạn có quyền ghi, ví dụ `D:\LumaNest`.
2. Mở **LumaNest.exe**. Máy đã cài môi trường: bấm **Mở ứng dụng**.
3. Máy mới: cài **Python 3.10–3.12 x64**, chọn tính năng rồi bấm **Cài đặt / sửa môi trường**. Cần Internet và khoảng 10 GB trống khi cài đầy đủ. Không cần quyền admin cho ứng dụng.
4. Khi cài xong, bấm **Mở ứng dụng**; trình duyệt mở `http://127.0.0.1:8000`.

EXE là trình mở/cài ứng dụng Windows; Python và model được cài riêng trong thư mục vừa giải nén. Gói ZIP không kèm dataset, ảnh cá nhân, API key hoặc trọng số. Sau khi tải model, các chức năng cục bộ chạy offline. Gemini/OpenAI cần kết nối mạng. Bản EXE được build từ `desktop/LumaNest.cs`, chưa có chứng thư ký mã.

## Có gì trong LumaNest?

- **Bộ ảnh:** tạo/đổi tên, tải ảnh, chống trùng, chuyển bộ, yêu thích, nhãn, ghi chú, lọc và tìm toàn văn.
- **Trình xem:** giữ trọn khung ảnh, tìm nhanh, chọn ảnh có thumbnail, so sánh trước/sau.
- **Tìm người:** MTCNN → căn chỉnh 5 điểm → AdaFace → cosine. Chọn mặt khi ảnh có nhiều người.
- **Tìm nội dung:** Google SigLIP 2 chạy cục bộ; tìm bằng mô tả tiếng Việt hoặc ảnh tương tự.
- **Nghệ thuật:** Candy, Mosaic, Rain Princess, Udnie; 512/768/1024 px; xử lý lô, tiếp tục, cache, tải PNG/ZIP.
- **Phong cách riêng:** ảnh tham chiếu → VGG19 tối ưu 50/150/300 bước cho từng ảnh; có tranh Van Gogh public domain từ The Met. Số bước không phải số ảnh.
- **Màu ảnh:** Cinema, Soft film, Noir, Nordic, Golden hour.
- **Chủ thể:** SAM 2.1 chọn vùng bằng điểm; PNG trong suốt, nền mờ hoặc nền nghệ thuật.
- **Trợ lý:** Qwen 3 trên máy hoặc Gemini API; hiểu mô tả phong cách và lập đề xuất. OpenAI là tùy chọn.
- **Bảo quản:** thùng rác/khôi phục, tải nguồn, checksum, hàng đợi và kiểm tra toàn vẹn.

Ảnh JPG/PNG/WebP tối đa **20 MB/file**, không áp trần megapixel; giới hạn RAM/codec vẫn tồn tại. Nguồn upload được giữ nguyên byte, thumbnail tạo riêng. Preset giữ tỉ lệ; VGG19 xử lý cạnh dài tối đa 512 px và chậm hơn preset.

## Cài từ mã nguồn

```powershell
python scripts/bootstrap.py --with-local-chat --with-subject-tools
.\.venv\Scripts\python.exe scripts/launch.py
```

Hoặc `./setup.ps1 -WithLocalChat -WithSubjectTools`, sau đó `./run.ps1`. Lược bớt tìm nội dung bằng `--skip-semantic-search`, bỏ tăng tốc bằng `--skip-cpu-optimization`, cài công cụ kiểm thử bằng `--with-dev`.

Cài đặt chỉ lấy thư viện từ PyPI/PyTorch và model upstream được liệt kê trong [THIRD_PARTY.md](THIRD_PARTY.md). Không tự tạo album hoặc tải ảnh demo. Một số tính năng tùy chọn chỉ hoạt động sau khi tải model tương ứng.

## Dữ liệu và quyền riêng tư

`runtime/` giữ ảnh, embedding, album và tác phẩm; `weights/` giữ model; `.venv/` giữ môi trường Python. Cả ba ở máy của bạn, nằm ngoài Git và gói phát hành. Sao lưu nguyên `runtime/` khi ứng dụng đã dừng; giữ `weights/` để tránh tải lại.

Nhận diện, tìm ảnh và NST chạy trên máy. Khi chọn Gemini/OpenAI, chỉ văn bản hội thoại được gửi; API tạo ảnh tham chiếu chỉ chạy sau thao tác tạo rõ ràng. Key nhập trong app chỉ giữ trong RAM server, tắt server phải nhập lại. Phí và hạn mức do nhà cung cấp API quy định.

Ứng dụng dùng cho máy cá nhân, mặc định chỉ lắng nghe loopback, chưa có đăng nhập/phân quyền nhiều người. Không mở cổng trực tiếp ra Internet. Cosine không phải xác suất; chưa có đánh giá accuracy trên tập độc lập của bạn. Xem [SECURITY.md](SECURITY.md).

## Hướng dẫn và kỹ thuật

- [Thao tác, phím tắt và khắc phục lỗi](docs/USAGE.vi.md)
- [Pipeline và cấu trúc hệ thống](docs/ARCHITECTURE.vi.md)
- [Nguồn model và giấy phép](THIRD_PARTY.md)

## Kiểm thử và đóng gói

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.cache/pytest-local
.\desktop\build.ps1
.\.venv\Scripts\python.exe scripts/package_release.py --windows
```

`dist/` nhận ZIP mã nguồn, ZIP Windows, manifest và SHA-256. Packager chỉ lấy danh sách thư mục/file đã cho phép, loại dữ liệu chạy và từ chối credential phổ biến trong mã nguồn. Trình mở Windows cần .NET Framework có sẵn trên Windows 10/11. Linux/macOS có thể dùng mã nguồn Python; chưa nghiệm thu trên hai hệ điều hành này.
