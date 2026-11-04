# Brief giao diện "Aurora 2026" cho LumaNest

Bạn phụ trách **phần đồ hoạ (CSS)**. Một agent khác (Claude) phụ trách lõi: JavaScript, HTML, backend, test, nghiệm thu. Hai bên làm song song trong cùng thư mục nên **ranh giới file dưới đây là bắt buộc**.

## Bối cảnh
- LumaNest là thư viện ảnh AI chạy hoàn toàn trên máy (FastAPI + JavaScript thuần, không framework, không bước build). Giao diện tiếng Việt.
- Frontend nằm ở `fsmart/static/`. Mở `fsmart/static/index.html` để xem thứ tự nạp CSS. `theme.css` nạp **đầu tiên** và chứa toàn bộ design token.
- App đang chạy sẵn tại **http://127.0.0.1:8766** (dữ liệu thử, có bộ ảnh "Smoke"). Sửa CSS xong thì tải lại trang để xem (Ctrl+Shift+R). **Không tự bật/tắt server.**
- Các trang: Bộ ảnh (collections), Ảnh (library), Tìm khuôn mặt (search), Sáng tạo (studio), Thùng rác (trash), Hệ thống (system). Ngoài ra có hộp thoại tạo bộ ảnh, lightbox xem ảnh, bảng lệnh Ctrl+K, khung trợ lý chat ở góc phải dưới, lớp phủ kéo-thả ảnh.

## Được sửa
- Mọi file `fsmart/static/*.css`, gồm cả `theme.css`.
- Được thêm file SVG trang trí vào `fsmart/static/illustrations/` và dùng qua `url()` trong CSS.

## Không được sửa
- **Không sửa** `*.js`, `*.py`, `index.html`, test, hay bất cứ thứ gì ngoài hai mục trên. Nếu cần đổi markup hay JS, ghi yêu cầu vào báo cáo (cuối file này), Claude sẽ làm.
- **Không đổi tên hay xoá** id/class đang có. JavaScript tra cứu chúng; đổi tên là app hỏng. Chỉ được *thêm* selector mới.
- **Không đổi chữ hiển thị** (kể cả qua `content:` trong CSS để thay chữ). Được thêm `content:` cho icon trang trí.
- **Không dùng tài nguyên mạng**: không CDN, không Google Fonts, không `@import url(http...)`. App phải chạy offline.
- **Không tạo file CSS mới** (để không thêm tầng ghi đè). Viết thẳng vào file của component tương ứng.
- Không chạy lệnh git làm thay đổi trạng thái (commit, checkout, reset, stash). Claude sẽ commit.

## Hướng thiết kế: "Aurora"
Hiện đại kiểu 2025–2026, nhiều màu, nổi bật nhưng vẫn sang và dễ đọc.

- **Mặc định nền tối.** Nền xanh-đen rất sâu (khoảng `#0b0d17`–`#11142a`). Phía sau có dải "aurora" mờ: các đốm gradient lớn tím `#8b5cf6`, hồng `#ec4899`, cam hổ phách `#f59e0b`, điểm xuyết xanh cyan `#22d3ee`. Vẽ bằng **một** lớp `body::before` cố định (`position:fixed; z-index:-1`), trôi rất chậm (40–60 giây một vòng).
- **Kính mờ (glassmorphism)** cho các bề mặt lớn: sidebar, topbar, hộp thoại, lightbox, khung chat, bảng lệnh. Nền bán trong suốt, `backdrop-filter: blur(...) saturate(...)`, viền sáng 1px kiểu `rgba(255,255,255,.08)`.
- **Màn hình Bộ ảnh** (`collections.css`): bố cục dạng **bento grid** với các ô kích cỡ khác nhau, ô đầu nổi bật hơn.
- **Nút chính:** nền gradient thương hiệu (tím → hồng → cam), chữ trắng, glow nhẹ, hover sáng và nhấc lên. Nút phụ: kính mờ, viền gradient mảnh.
- **Card ảnh:** bo góc lớn, hover nhấc lên (`translateY` + shadow), ảnh phóng nhẹ trong khung. Huy hiệu và sao yêu thích nổi bật trên ảnh.
- **Form:** ô nhập nền tối trong suốt, focus có vòng gradient hoặc glow rõ ràng.
- **Chuyển động:** dùng chung `--ease-spring` và các token thời lượng. Chỉ animate `transform` và `opacity`.
- **Chữ:** `--font-body` = `"Be Vietnam Pro", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` (Claude sẽ thêm file font sau; trước đó máy dùng Segoe UI). Tiêu đề lớn có thể dùng chữ gradient (`background-clip:text`). Bỏ font serif Georgia, trừ khi bạn thấy cần nó cho điểm nhấn.

### Token trong `theme.css`
Định nghĩa đủ bộ token ngữ nghĩa, ví dụ:
`--bg`, `--surface-1/2/3`, `--glass`, `--glass-border`, `--text`, `--text-muted`, `--accent-violet`, `--accent-pink`, `--accent-amber`, `--accent-cyan`, `--gradient-brand`, `--gradient-aurora`, `--success`, `--warning`, `--danger`, `--shadow-sm/md/lg`, `--glow`, `--radius-sm/md/lg/xl`, `--ease-spring`, `--dur-fast/base/slow`.

- **Giữ các tên token cũ** (`--paper`, `--white`, `--soft`, `--line`, `--ink`, `--muted`, `--on-dark`, `--green`, `--orange`, `--focus`, `--font-body`, `--font-display`, `--radius`) dưới dạng **alias** trỏ sang token mới, để CSS cũ vẫn chạy. Ví dụ `--white` là màu nền card: ở chế độ tối nó trỏ sang `var(--surface-1)`.
- **Chế độ sáng:** đặt trong `:root[data-theme="light"] { ... }`. Claude sẽ thêm nút chuyển sáng/tối, gắn `data-theme` lên `<html>`. Chế độ tối là `:root` mặc định.
- **Bỏ màu hex cứng:** ngoài `theme.css` hiện còn khoảng 245 mã hex lẻ. Hãy thay hết bằng token. Mục tiêu: ngoài `theme.css` không còn mã hex nào (trừ trong `url(data:...)`).

## Yêu cầu chất lượng
- **Hiệu năng:** `backdrop-filter` chỉ dùng trên vài bề mặt lớn liệt kê ở trên, **không bao giờ** dùng trên `.photo-card` hay phần tử lặp lại (thư viện có thể có hàng nghìn ảnh). Không dùng `filter: blur` trên ảnh trong lưới.
- **Truy cập:** chữ thường đạt tương phản ≥ 4.5:1, chữ lớn ≥ 3:1, ở cả chế độ tối và sáng. Vòng focus (`:focus-visible`) phải thấy rõ trên nền tối. Không truyền tải thông tin chỉ bằng màu. Vùng bấm ≥ 36px.
- **Giảm chuyển động:** trong `@media (prefers-reduced-motion: reduce)` thì tắt aurora trôi và các animation trang trí.
- **Responsive:** giữ hoạt động ở 375px, 768px và màn rộng. Các media query đang có phải còn chạy đúng.
- **Trạng thái:** hover, active, disabled (`button:disabled`), `.hidden`, `[aria-pressed="true"]`, `[aria-selected="true"]`, `.active`, `.selected`, `.is-favorite`, `.has-selection` phải nhìn rõ khác biệt.

## Tự kiểm tra trước khi báo xong
1. Chạy test khế ước giao diện (phải pass):
   `D:\prjdpl\.venv\Scripts\python.exe -m pytest -q --basetemp=.cache/pytest-local tests/test_frontend_contract.py`
2. Mở http://127.0.0.1:8766 và xem từng trang, cả hộp thoại, lightbox (bấm vào ảnh), Ctrl+K, khung chat. Xem ở bề ngang 375px và 1440px.
3. Đếm hex còn sót: `grep -oE "#[0-9a-fA-F]{3,8}\b" fsmart/static/*.css | grep -v theme.css` (mục tiêu: rỗng).

## Báo cáo khi xong
Tạo `docs/ui/ANTIGRAVITY_REPORT.md`, gồm:
- danh sách file đã sửa, mỗi file một dòng mô tả;
- các token đã định nghĩa;
- **yêu cầu cho Claude**: những chỗ cần đổi HTML/JS (ví dụ thêm wrapper, thêm class, icon SVG trong markup);
- những gì chưa làm xong hoặc còn băn khoăn.
