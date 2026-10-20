# Dùng LumaNest

## Bắt đầu

Giải nén toàn bộ gói Windows vào thư mục có quyền ghi. Mở `LumaNest.exe`; lần đầu chọn tính năng rồi bấm **Cài đặt / sửa môi trường**. Khi đã có môi trường, bấm **Mở ứng dụng**. EXE mở server nền và trình duyệt; đóng cửa sổ launcher không tắt server.

Trong **Thư viện ảnh**, tạo bộ mới, mở bộ rồi thêm ảnh. Chờ lập chỉ mục mặt hoàn tất. Mỗi bộ có **Ảnh / Tìm khuôn mặt / Sáng tạo / Thùng rác**. Không có ảnh demo tự tạo.

## Tìm và chỉnh ảnh

Tìm người: tải ảnh rõ mặt trong mục **Tìm khuôn mặt**, chọn mặt đúng, kiểm tra bộ ảnh và ngưỡng. Không có kết quả có thể do thiếu chỉ mục, góc mặt hoặc ngưỡng. Hạ ngưỡng có thể tăng kết quả sai.

Tìm mô tả: cài SigLIP 2, cập nhật chỉ mục AI trong bộ ảnh rồi nhập câu tiếng Việt. Kết quả tương tự nội dung không xác nhận cùng người.

Sáng tạo nhanh: chọn preset và mức 512 px. Tạo cả bộ hoặc các ảnh đã tích bằng nút tương ứng. Phong cách Van Gogh/ảnh tham chiếu dùng VGG19 tối ưu từng ảnh; **“Bước tối ưu 1/50 · 1 ảnh”** là 50 bước trên một ảnh. Chọn mức bước cao hơn sẽ chờ lâu hơn.

Chat: chọn Qwen trên máy hoặc Gemini, nhập key ở cài đặt rồi **Lưu và kiểm tra**. Kiểm tra kết nối không chứng minh tài khoản có quota tạo ảnh. API ảnh có thể tính phí riêng. Chọn ảnh, mô tả phong cách, duyệt đề xuất và bấm tạo.

## Phím tắt

| Phím | Thao tác |
|---|---|
| Ctrl K | Tìm thao tác |
| ← / → | Chuyển ảnh trong trình xem |
| F | Yêu thích |
| E | Mở sáng tạo |
| Esc | Đóng trình xem |

## Dữ liệu và khắc phục lỗi

- Ảnh, album, embedding, tác phẩm nằm trong `runtime/`; model ở `weights/`. Không xóa hai thư mục này khi muốn giữ dữ liệu.
- Chuyển ảnh vào **Thùng rác** có thể khôi phục; xóa vĩnh viễn cần xác nhận riêng.
- Thiếu model: bấm **Cài đặt / sửa môi trường**; các file đã tải được dùng lại khi có thể.
- Không khởi động: xem `runtime/logs/server-error.log`; kiểm tra cổng 8000. Không chạy nhiều bản ứng dụng dùng cùng thư mục runtime.
- Quá chậm: dùng preset 512 px với OpenVINO; VGG19 khác pipeline và chậm hơn. Tác vụ lô có dừng/tiếp tục.
- Để tắt server nền: đóng đúng tiến trình Python chạy `uvicorn fsmart.app:app` của thư mục này trong Task Manager. Không kết thúc các tiến trình Python khác.
- Trước khi sao lưu/nâng cấp, đợi tác vụ xong và dừng server, sao chép nguyên `runtime/`. Không lấy dữ liệu cá nhân đưa vào gói chia sẻ.
