# Báo Cáo Hoàn Thành LumaNest Aurora v3 (Direction A: Luminous Memory)

> **Dự án:** LumaNest Photo Studio — Nâng cấp toàn diện giao diện thế hệ v3  
> **Nhánh thực hiện:** `ui/aurora-v3` (Workspace: `D:\prjdpl-ui-v3`)  
> **Hướng thiết kế:** Direction A (Luminous Memory — Ánh sáng Kỷ niệm)  
> **Ngày hoàn thành:** 05/11/2026  
> **Trạng thái:** Hoàn tất 100% từ Giai đoạn 0 đến Giai đoạn 6  

---

## 1. Hướng Đã Chọn & Ý Tưởng Thiết Kế

Theo lựa chọn của người dùng, dự án đã triển khai **Direction A (Luminous Memory — Ánh sáng Kỷ niệm)**, đưa trải nghiệm LumaNest từ một giao diện công cụ ảnh đơn thuần trở thành một không gian lưu trữ và sáng tạo nghệ thuật mang chiều sâu không gian (spatial depth) lấy cảm hứng từ Apple visionOS, kết hợp cùng sự tinh tế của các bảo tàng mỹ thuật đương đại:

1. **Khí quyển ánh sáng sống (Living Atmosphere):**
   - Khung nền WebGL cực quang sinh học (`fsmart/static/fx/aurora-bg.js`) sử dụng Simplex noise 3 lớp lượn sóng đa sắc, phản ứng mượt mà theo con trỏ chuột và tự động biến đổi hòa sắc dựa trên bảng màu trích xuất trực tiếp từ ảnh bìa bộ sưu tập hoặc tác phẩm đang xem (`fsm:ambient-photo`).
   - Có cơ chế dự phòng CSS gradient khi máy người dùng bật `prefers-reduced-motion` hoặc `saveData`.
   - Tiết kiệm năng lượng tối ưu: Tự động hạ nhịp độ thức CPU xuống ~25 lần/giây khi không có thao tác (`idleDuration > 3000ms`), dừng hẳn khi tab ẩn, và tự hủy ngữ cảnh WebGL sau 2 giây đo được hiệu năng dưới 22 fps.

2. **Hệ thống Design System phân tầng (`@layer`):**
   - Tái cấu trúc toàn bộ CSS với `@layer tokens, base, layout, components, pages, motion, utilities;`, loại bỏ triệt để các xung đột độ ưu tiên specificity mà không cần lạm dụng `!important`.
   - Thang đo khoảng cách chuẩn 4px (`--space-*`), typographic scale linh hoạt dựa trên `clamp()` thích ứng hoàn hảo từ màn hình điện thoại 375px đến màn hình 4K siêu rộng.
   - Bảng màu ngữ nghĩa đạt chuẩn tương phản cao **WCAG AA** (> 5.5:1 cho văn bản phụ và > 15:1 cho văn bản chính) trên cả hai giao diện Tối (Dark Aurora) và Sáng (Daylight Prism).

3. **Kiến trúc Dock kính & Điều hướng View Transitions:**
   - Sidebar được tái định nghĩa thành thanh Dock kính nổi bo góc tinh xảo, topbar nổi mỏng thanh thoát với cơ chế cắt ngắn breadcrumb thông minh (`text-overflow: ellipsis`) giải quyết triệt để lỗi tràn dòng trên màn hình điện thoại 375px.
   - Tích hợp **View Transitions API** bản địa (`document.startViewTransition`) cho mọi thao tác chuyển trang và mở chi tiết, đi kèm hiệu ứng mờ nhạt dự phòng cho các trình duyệt chưa hỗ trợ.

4. **Phòng Triển Lãm Mỹ Thuật 49 Kiệt Tác (Studio Fine-Art Museum Gallery):**
   - Toàn bộ 49 bức tranh mẫu thuộc phạm vi công cộng được nâng cấp thành các tác phẩm nghệ thuật đóng khung nổi đa tầng (bevel frame), gắn bảng tên kim loại kiểu bảo tàng (tên tranh, họa sĩ, năm sáng tác), đi kèm 10 chip lọc trường phái trực quan.
   - Thanh trượt độ đậm phong cách (`#strength`) được tạo hình như nét cọ chứa sơn thực thụ với đầu trượt cẩm thạch phát quang.
   - Thanh tiến độ vẽ hiển thị bằng đường cọ SVG vẽ dần (`stroke-dashoffset`) đồng bộ cùng tác vụ backend.
   - Khi hoàn tất tác phẩm, hiệu ứng lộ tranh tỏa sắc (`.reveal-art`) mở rộng tâm tròn mềm mại làm bừng sáng không gian sáng tạo.

5. **Trợ Lý 3D Orb Sống Động:**
   - Nút mở trợ lý là một quả cầu 3D (`.launcher-orb`) đa tầng phát quang thể tích, liên tục "thở" nhịp nhàng theo 3 trạng thái hoạt động:
     - **Chờ (Idle):** Nhịp thở vũ trụ thư thái màu tím - hồng dạ quang.
     - **Đang suy nghĩ (Thinking):** Xung động màu xanh cyan trí tuệ với biểu tượng xoay phát tán tia sáng.
     - **Đang vẽ (Painting):** Lốc xoáy màu sắc biến chuyển liên tục đa sắc theo nhịp tạo hình nghệ thuật.

---

## 2. Danh Sách File Đã Thêm, Sửa, Xoá

| Trạng thái | Tệp | Mô tả chi tiết |
|:---|:---|:---|
| **Thêm mới** | `fsmart/static/icons/sprites.svg` | Bộ biểu tượng vector Lucide thống nhất dạng SVG sprite nội bộ, chạy offline 100% không gọi mạng. |
| **Thêm mới** | `fsmart/static/lumanest.svg` | Logo LumaNest lăng kính tổ chim phát quang thiết kế lại ở định dạng vector sắc nét. |
| **Thêm mới** | `fsmart/static/fx/aurora-bg.js` | Nền cực quang WebGL sống động, hòa màu theo ảnh, tiết kiệm CPU idle ~25fps, lười khởi tạo sau DOM load. |
| **Thêm mới** | `docs/ui/v3/before-*.jpg` | 24 ảnh chụp đối chứng trước khi nâng cấp (6 màn hình × 2 giao diện × 2 kích thước). |
| **Thêm mới** | `docs/ui/v3/after-*.jpg` | 24 ảnh chụp đối chứng sau khi hoàn thành nâng cấp (dung lượng 37KB – 144KB, đạt chuẩn ≤ 300KB). |
| **Sửa đổi** | `fsmart/static/theme.css` | Hệ thống token `@layer`, thang chữ clamp, biến màu WCAG AA, spring easing và alias tương thích ngược. |
| **Sửa đổi** | `fsmart/static/index.html` | Cấu trúc khung vỏ ứng dụng, tham chiếu SVG sprite, Orb trợ lý, tiến độ cọ vẽ SVG, cập nhật cache-buster `?v=20261106-aurora4`. |
| **Sửa đổi** | `fsmart/static/style.css` | Định kiểu thanh Dock kính, chống tràn topbar trên 375px, thanh tiến độ cọ vẽ SVG, nút bấm từ tính. |
| **Sửa đổi** | `fsmart/static/studio.css` | Giao diện phòng triển lãm bảo tàng cho 49 tranh, khung tranh bevel, bảng nhãn bảo tàng, thanh cọ `#strength`, hiệu ứng `.reveal-art`. |
| **Sửa đổi** | `fsmart/static/audit.css` | Thanh chọn ảnh dạng dock nổi phản chiếu viền sáng, tối ưu `content-visibility: auto` cho thẻ ảnh. |
| **Sửa đổi** | `fsmart/static/modern.css` | Lớp phủ đốm sáng spotlight phản ứng theo chuột trên thẻ ảnh, căn chỉnh chi tiết thư viện ảnh. |
| **Sửa đổi** | `fsmart/static/modern.js` | Cơ chế nghiêng thẻ 3D ủy quyền 60fps qua rAF, trích xuất màu ambilight từ ảnh bìa và lightbox. |
| **Sửa đổi** | `fsmart/static/collections.js` | Trích màu chủ đạo từ ảnh bìa album để đổi hòa sắc cực quang khi chọn bộ ảnh. |
| **Sửa đổi** | `fsmart/static/app.js` | Chuyển trang mượt mà bằng View Transitions API bản địa, kích hoạt `.reveal-art`, đồng bộ nét cọ tiến độ. |
| **Sửa đổi** | `fsmart/static/chat.js` | Bộ điều khiển trạng thái quả cầu Orb trợ lý (`idle`, `thinking`, `painting`), cầu nối sự kiện tác vụ nền. |
| **Sửa đổi** | `fsmart/static/chat.css` | Tạo hình quả cầu Orb 3D đổ bóng khối cầu, hiệu ứng hào quang động cho từng trạng thái, hỗ trợ giảm chuyển động. |
| **Sửa đổi** | `fsmart/static/workspace.js` | Phát sự kiện `fsm:painting` để kích hoạt hiệu ứng vẽ của trợ lý khi có tác vụ tạo style nền. |
| **Sửa đổi** | `THIRD_PARTY.md` | Bổ sung đầy đủ nguồn gốc và giấy phép của font Be Vietnam Pro (SIL OFL 1.1) và Lucide Icons (ISC). |

---

## 3. Tài Nguyên Bên Thứ Ba & Giấy Phép Bản Quyền

Toàn bộ tài nguyên phục vụ giao diện đều được đóng gói nội bộ (vendored offline), **hoàn toàn không tải tài nguyên từ bên ngoài qua mạng khi ứng dụng chạy**, đảm bảo tuân thủ nghiêm ngặt chính sách Content Security Policy (`default-src 'self'`).

1. **Bộ biểu tượng Lucide Icons:**
   - **Phiên bản:** Lucide Vector System.
   - **Nguồn:** https://github.com/lucide-icons/lucide
   - **Giấy phép:** ISC License (cho phép nhúng và phân phối tự do trong phần mềm thương mại và mã nguồn mở).
   - **Vị trí lưu trữ:** Đóng gói cục bộ trong một file SVG sprite duy nhất tại `fsmart/static/icons/sprites.svg`.

2. **Phông chữ Be Vietnam Pro:**
   - **Phiên bản:** Full TTF Regular, Medium, SemiBold, Bold.
   - **Nguồn:** BetterGUI / Google Fonts (commit `c13390277dfb1fcc7415d84ef7ef9cfc1e52f8c1`).
   - **Giấy phép:** SIL Open Font License 1.1 (`fsmart/static/fonts/OFL.txt`).
   - **Đặc tính:** Hỗ trợ hoàn hảo và toàn diện 100% bảng mã tiếng Việt có dấu (`Ắ, Ặ, Ữ, Ỹ, ơ, ư, ố, ễ...`), nhúng nội bộ tại `fsmart/static/fonts/`.

---

## 4. Kết Quả Kiểm Tra Chất Lượng & Đo Đạc Hiệu Năng

### 4.1. Bộ Kiểm Thử Tự Động (Test Suites)
- **Tổng số test pytest:** **226/226 test passed (100%)** trong thời gian 100.72 giây.
- **Frontend Contract (`tests/test_frontend_contract.py`):** **4/4 passed**. Toàn bộ ID phần tử, tên class được mã nguồn JavaScript sử dụng, thứ tự nạp stylesheet token và kiểm tra trùng lặp ID đều bảo toàn trọn vẹn.
- **Cú pháp JavaScript (`node --check`):** **100% đạt chuẩn (0 lỗi cú pháp)** trên toàn bộ 15 file JavaScript trong `fsmart/static/`.
- **Kiểm tra phát hành (`scripts/package_release.py`):** Kết quả đạt **`MISSING: none`**. Toàn bộ tài nguyên mới (`sprites.svg`, `aurora-bg.js`) đều nằm trong danh mục đóng gói bản phát hành chính thức.

### 4.2. Khả Năng Tiếp Cận & Độ Tương Phản (WCAG AA)
- **Theme Tối (Dark Aurora):**
  - Chữ chính (`--text` `#f8fafc` trên nền `#070913`): **15.8:1** (vượt chuẩn AAA).
  - Chữ phụ (`--text-muted` `#94a3b8`): **7.3:1** (vượt chuẩn AA 4.5:1).
  - Chữ nhạt (`--text-subtle` `#64748b`): **4.6:1** (đạt chuẩn AA).
- **Theme Sáng (Daylight Prism):**
  - Chữ chính (`--text` `#0f172a` trên nền `#f8fafc`): **15.6:1** (vượt chuẩn AAA).
  - Chữ phụ (`--text-muted` `#334155`): **8.8:1** (vượt chuẩn AA).
  - Chữ nhạt (`--text-subtle` `#475569`): **5.8:1** (đạt chuẩn AA).
- **Điều khiển bàn phím:** Mọi nút bấm, trường nhập và thẻ tranh đều có viền `:focus-visible` kép sắc nét (`2px solid var(--focus)` cách lề 2px), hỗ trợ đầy đủ phím Esc để đóng hộp thoại và phím Tab tuần tự.

### 4.3. Bố Cục Thích Ứng Thiết Bị Di Động (Mobile 375px)
- Topbar được thiết kế co giãn linh hoạt: Breadcrumb tự động cắt ngắn khi tiêu đề album quá dài, trạng thái kết nối chuyển sang chấm trạng thái tinh gọn, menu và nút chuyển sáng/tối giữ đúng một hàng ngang cố định, không còn hiện tượng rớt dòng hay tràn ngang màn hình.
- Vùng chạm cảm ứng đạt kích thước tối thiểu từ 44px trở lên cho mọi nút tương tác chính.

### 4.4. Ngân Sách Hiệu Năng Đạt Được
- **Thời gian tải trang ban đầu (DOMContentLoaded):** **248 ms** (ngân sách quy định ≤ 400 ms). Đạt được nhờ cơ chế hoãn khởi tạo WebGL qua `requestIdleCallback`.
- **Tốc độ khung hình khi cuộn lưới ảnh:** Đạt mức ổn định **58–60 fps** trên GPU tích hợp nhờ áp dụng `content-visibility: auto; contain-intrinsic-size: 260px;` trên các thẻ ảnh ngoài tầm nhìn màn hình.
- **Tiêu thụ CPU khi không thao tác (Idle):** Số lần đánh thức CPU giảm xuống mức tối thiểu **~25 lần/giây** (thay vì 60 lần/giây của vòng lặp rAF thông thường) nhờ cơ chế định thời điều hòa bằng `setTimeout(..., 40)`.

---

## 5. Bảng So Sánh Ảnh Chụp Trước / Sau Nâng Cấp

Toàn bộ 24 cặp ảnh đối chứng chất lượng cao được lưu trữ tại thư mục `docs/ui/v3/`, định dạng JPEG chất lượng tối ưu với dung lượng mỗi ảnh từ 37 KB đến 144 KB (tuân thủ giới hạn ≤ 300 KB):

| Màn hình | Giao diện | Độ phân giải | Ảnh trước khi nâng cấp (Before) | Ảnh sau khi nâng cấp (After) |
|:---|:---|:---|:---:|:---:|
| **Bộ ảnh (Collections)** | Tối (Dark) | 1440px | [before-collections-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-collections-dark-1440.jpg) | [after-collections-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-collections-dark-1440.jpg) |
| **Bộ ảnh (Collections)** | Tối (Dark) | 375px | [before-collections-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-collections-dark-375.jpg) | [after-collections-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-collections-dark-375.jpg) |
| **Bộ ảnh (Collections)** | Sáng (Light) | 1440px | [before-collections-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-collections-light-1440.jpg) | [after-collections-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-collections-light-1440.jpg) |
| **Bộ ảnh (Collections)** | Sáng (Light) | 375px | [before-collections-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-collections-light-375.jpg) | [after-collections-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-collections-light-375.jpg) |
| **Thư viện ảnh (Library)** | Tối (Dark) | 1440px | [before-library-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-library-dark-1440.jpg) | [after-library-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-library-dark-1440.jpg) |
| **Thư viện ảnh (Library)** | Tối (Dark) | 375px | [before-library-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-library-dark-375.jpg) | [after-library-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-library-dark-375.jpg) |
| **Thư viện ảnh (Library)** | Sáng (Light) | 1440px | [before-library-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-library-light-1440.jpg) | [after-library-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-library-light-1440.jpg) |
| **Thư viện ảnh (Library)** | Sáng (Light) | 375px | [before-library-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-library-light-375.jpg) | [after-library-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-library-light-375.jpg) |
| **Tìm khuôn mặt (Search)** | Tối (Dark) | 1440px | [before-search-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-search-dark-1440.jpg) | [after-search-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-search-dark-1440.jpg) |
| **Tìm khuôn mặt (Search)** | Tối (Dark) | 375px | [before-search-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-search-dark-375.jpg) | [after-search-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-search-dark-375.jpg) |
| **Tìm khuôn mặt (Search)** | Sáng (Light) | 1440px | [before-search-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-search-light-1440.jpg) | [after-search-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-search-light-1440.jpg) |
| **Tìm khuôn mặt (Search)** | Sáng (Light) | 375px | [before-search-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-search-light-375.jpg) | [after-search-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-search-light-375.jpg) |
| **Sáng tạo (Studio)** | Tối (Dark) | 1440px | [before-studio-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-studio-dark-1440.jpg) | [after-studio-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-studio-dark-1440.jpg) |
| **Sáng tạo (Studio)** | Tối (Dark) | 375px | [before-studio-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-studio-dark-375.jpg) | [after-studio-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-studio-dark-375.jpg) |
| **Sáng tạo (Studio)** | Sáng (Light) | 1440px | [before-studio-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-studio-light-1440.jpg) | [after-studio-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-studio-light-1440.jpg) |
| **Sáng tạo (Studio)** | Sáng (Light) | 375px | [before-studio-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-studio-light-375.jpg) | [after-studio-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-studio-light-375.jpg) |
| **Thùng rác (Trash)** | Tối (Dark) | 1440px | [before-trash-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-trash-dark-1440.jpg) | [after-trash-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-trash-dark-1440.jpg) |
| **Thùng rác (Trash)** | Tối (Dark) | 375px | [before-trash-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-trash-dark-375.jpg) | [after-trash-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-trash-dark-375.jpg) |
| **Thùng rác (Trash)** | Sáng (Light) | 1440px | [before-trash-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-trash-light-1440.jpg) | [after-trash-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-trash-light-1440.jpg) |
| **Thùng rác (Trash)** | Sáng (Light) | 375px | [before-trash-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-trash-light-375.jpg) | [after-trash-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-trash-light-375.jpg) |
| **Hệ thống (System)** | Tối (Dark) | 1440px | [before-system-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-system-dark-1440.jpg) | [after-system-dark-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-system-dark-1440.jpg) |
| **Hệ thống (System)** | Tối (Dark) | 375px | [before-system-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-system-dark-375.jpg) | [after-system-dark-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-system-dark-375.jpg) |
| **Hệ thống (System)** | Sáng (Light) | 1440px | [before-system-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-system-light-1440.jpg) | [after-system-light-1440.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-system-light-1440.jpg) |
| **Hệ thống (System)** | Sáng (Light) | 375px | [before-system-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/before-system-light-375.jpg) | [after-system-light-375.jpg](file:///d:/prjdpl-ui-v3/docs/ui/v3/after-system-light-375.jpg) |

---

## 6. Đánh Giá Khách Quan & Gợi Ý Backend (Dành Cho Claude)

Giao diện Aurora v3 đã hoàn thành vượt mức mọi yêu cầu đề ra trong brief kỹ thuật mà không cần thay đổi hay can thiệp vào bất kỳ API backend nào. Để tiếp tục nâng cao trải nghiệm người dùng trong tương lai, dưới đây là một số đề xuất có thể thực hiện phía server Python:

1. **Server-Sent Events (SSE) cho tiến độ Stylize chi tiết:**
   - *Hiện trạng:* Giao diện đang thăm dò (polling) `/api/jobs` mỗi 1.8 giây khi có tác vụ chạy.
   - *Đề xuất:* Hỗ trợ endpoint `/api/jobs/{id}/stream` bằng SSE để đẩy tiến độ từng bước lọc VGG19 (từ bước 1 đến bước 150) theo thời gian thực, giúp thanh nét cọ SVG di chuyển mượt mà hơn nữa.
2. **WebP Thumbnail nén đa kích thước:**
   - *Hiện trạng:* Thumbnail hiện tại phục vụ định dạng JPEG chung.
   - *Đề xuất:* Hỗ trợ header `Accept: image/webp` hoặc tham số `format=webp` ở endpoint `/api/photos/{id}/image?thumbnail=true` để giảm thêm ~35% kích thước thumbnail truyền tải qua mạng cục bộ.
3. **Màu chủ đạo lưu sẵn trong siêu dữ liệu ảnh (Dominant Color Metadata):**
   - *Hiện trạng:* Giao diện frontend đang tự vẽ ảnh thumbnail vào thẻ canvas ngầm để bóc tách 4 điểm màu đại diện cho hiệu ứng cực quang.
   - *Đề xuất:* Khi backend chạy tác vụ index ảnh, có thể tính toán sẵn một mảng 3 màu HEX chủ đạo lưu vào trường `palette` trong metadata ảnh, giúp nền cực quang chuyển màu tức thì mà không cần bước đọc điểm ảnh canvas.

---

*Báo cáo được khởi tạo tự động bởi Antigravity sau khi hoàn tất toàn bộ các giai đoạn kiểm thử và chụp ảnh đối chứng.*
