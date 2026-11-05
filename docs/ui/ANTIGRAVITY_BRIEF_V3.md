# Brief giao diện "Aurora v3": đổi mới toàn diện LumaNest

Bạn (Antigravity) phụ trách **toàn bộ lớp giao diện** của LumaNest: hình ảnh, bố cục, chuyển động, 3D, chữ, icon, minh hoạ. Mục tiêu là giao diện **đẹp nhất có thể**, ngang tầm các trang được giải trên Awwwards hay ứng dụng Apple, nhưng vẫn **nhanh, dễ đọc, chạy offline và không làm hỏng chức năng nào**.

Đọc hết file này trước khi sửa bất cứ thứ gì. Làm theo từng giai đoạn ở mục 12, commit sau mỗi giai đoạn.

---

## 1. Bối cảnh kỹ thuật

- LumaNest là thư viện ảnh AI chạy hoàn toàn trên máy: FastAPI (Python) + **JavaScript thuần, không framework, không bước build**. Giao diện tiếng Việt.
- **Thư mục làm việc: `D:\prjdpl-ui-v3`** (git worktree của repo `D:\prjdpl`, nhánh `ui/aurora-v3`). `D:\prjdpl` là bản người dùng đang dùng hằng ngày: **không sửa gì ở đó**, chỉ dùng `.venv` và `weights` của nó. Frontend nằm ở `fsmart/static/`: `index.html`, 14 file JS, 13 file CSS (`theme.css` chứa design token), `fonts/` (Be Vietnam Pro, OFL), `illustrations/` (11 SVG).
- Giao diện hiện tại là "Aurora 2026" (nền tối, cực quang tím–hồng–cam, kính mờ). Bạn được **làm lại từ đầu** về mặt thị giác, không cần giữ phong cách cũ.
- Các trang: **Bộ ảnh** (collections), **Ảnh** (library), **Tìm khuôn mặt** (search), **Sáng tạo** (studio), **Thùng rác** (trash), **Hệ thống** (system). Ngoài ra: hộp thoại tạo bộ ảnh, lightbox xem ảnh, thanh chọn nhiều ảnh, bảng lệnh Ctrl+K, lớp phủ kéo-thả ảnh, khung trợ lý chat (góc phải dưới) với phần cài đặt nguồn model, bảng tác vụ/tiến độ, toast, hộp xác nhận.
- Phòng Sáng tạo có: 4 preset (Candy, Mosaic, Rain Princess, Udnie), "Style của bạn" (tải ảnh phong cách), **Thư viện tranh 49 phong cách** (10 nhóm, tranh phạm vi công cộng), thanh độ đậm, chọn tốc độ/kích thước, 6 bảng màu (Nguyên bản, Cinema, Soft film, Noir, Nordic, Golden hour), tách chủ thể bằng điểm chọn (SAM 2.1), xử lý theo lô, so sánh trước/sau, lịch sử tác phẩm.
- Tên ứng dụng hiển thị **giữ nguyên là "LumaNest"** (chưa đổi thương hiệu).

### CSP của server (không được nới lỏng)

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
```

Hệ quả bắt buộc:
- **Không** `<script>` nội tuyến, **không** thuộc tính `onclick=`/`onload=`… trong HTML. Mọi JS nằm trong file `.js` dưới `/static/`.
- **Không** CDN, Google Fonts, unpkg, jsDelivr, ảnh/video từ Internet. Mọi tài nguyên phải nằm trong `fsmart/static/`.
- **Không** `eval`, `new Function`, **không WebAssembly** (CSP không cho `wasm-unsafe-eval`), nên không dùng runtime Rive/dotLottie bản WASM.
- **Được**: `<script type="module" src="/static/...">`, `import()` động từ `/static/`, Web Worker từ file cùng nguồn, WebGL/WebGL2, Canvas, CSS nội tuyến và `element.style`, ảnh `data:`/`blob:`.

## 2. Nơi làm việc và git

Claude đã tạo sẵn worktree `D:\prjdpl-ui-v3` trên nhánh `ui/aurora-v3` (từ `origin/main`). Kiểm tra trước khi sửa:

```powershell
cd D:\prjdpl-ui-v3
git branch --show-current   # phải in ra ui/aurora-v3
```

- Làm toàn bộ trong `D:\prjdpl-ui-v3`, trên nhánh `ui/aurora-v3`. Commit nhỏ, mỗi giai đoạn ít nhất một commit, message tiếng Anh mô tả rõ.
- **Không** push, merge, rebase, `reset --hard`, `stash`, xoá nhánh, hay đổi sang nhánh khác.
- **Không** sửa, xoá hay chạy lệnh git nào trong `D:\prjdpl` (bản đang dùng, có dữ liệu thật và gói phát hành 1.1.0).
- Commit brief này (`docs/ui/ANTIGRAVITY_BRIEF_V3.md`) trong commit đầu tiên.

## 3. Chạy thử với dữ liệu mẫu

**Không dùng dữ liệu thật trong `runtime/`** (ảnh cá nhân của người dùng). Bật một server riêng với thư mục dữ liệu riêng:

```powershell
cd D:\prjdpl-ui-v3          # bắt buộc: server nạp mã giao diện từ thư mục đang đứng
$env:FSM_WEIGHTS_DIR = 'D:\prjdpl\weights'
$env:FSM_DATA_DIR    = 'D:\prjdpl-ui-v3\.cache\ui-demo'
D:\prjdpl\.venv\Scripts\python.exe -m uvicorn fsmart.app:app --host 127.0.0.1 --port 8790
```

- Mở **http://127.0.0.1:8790** (dùng đúng host này, không trộn `localhost` với `127.0.0.1`).
- Tạo bộ ảnh "Demo" và tải lên 20–40 ảnh từ `D:\prjdpl\weights\artworks\*.jpg` (tranh phạm vi công cộng, có chân dung để thử tìm khuôn mặt). Tạo thêm 2–3 bộ ảnh nữa để màn Bộ ảnh có nội dung.
- **Không tắt** các server khác đang chạy (cổng 8000, 8765). Chỉ tắt server 8790 của bạn.
- Mọi ảnh chụp màn hình đưa vào repo **chỉ được dùng dữ liệu mẫu này**.

## 4. Phạm vi sửa

**Được sửa / thêm**
- Mọi file trong `fsmart/static/` (HTML, CSS, JS, SVG, font, ảnh).
- Được tạo file CSS/JS mới, thư mục mới (ví dụ `fsmart/static/fx/`, `fsmart/static/vendor/`, `fsmart/static/icons/`), được gom và sắp xếp lại 13 file CSS.
- Sửa JS hiện có **chỉ để gắn hiệu ứng** (thêm class, bọc lời gọi bằng View Transition, phát sự kiện…). **Không đổi** logic gọi API, dữ liệu gửi đi, thứ tự luồng nghiệp vụ.
- `THIRD_PARTY.md` (ghi nguồn thư viện/tài nguyên mới), `docs/ui/` (báo cáo, ảnh chụp).
- `scripts/package_release.py`: **chỉ** được thêm đuôi file vào `SUFFIXES` nếu bạn dùng loại file mới (ví dụ `.woff2`, `.webp`, `.png`, `.glb`). Gói phát hành chỉ lấy các đuôi trong danh sách này; thiếu là bản phát hành bị mất tài nguyên.

**Không được sửa**
- Mọi file `.py` khác, API, CSP, test (trừ khi thêm test mới cho frontend), `requirements*.txt`, `desktop/`, `runtime/`, `weights/`, `.venv/`.
- **Không đổi tên hay xoá id/class mà JS đang dùng.** Test `tests/test_frontend_contract.py` kiểm tra điều này; phải luôn pass. Được thêm id/class mới.
- **Không đổi nội dung chữ tiếng Việt** (trừ sửa lỗi chính tả, dấu). Được thay icon ký tự (▦ ◎ ⌕ ✳ ⌫ ↗ …) bằng icon SVG, giữ nguyên nhãn chữ.
- **Không bỏ tính năng nào**, không ẩn nút đang có.
- Không thêm framework (React, Vue, Svelte…), không thêm bước build bắt buộc. Nếu cần lấy thư viện qua npm thì làm trong thư mục tạm **ngoài repo**, rồi chép file `dist` đã build sẵn vào `fsmart/static/vendor/<tên>-<phiên bản>/` kèm file LICENSE.
- Không thêm analytics, tracking, font/ảnh tải từ mạng, không gửi ảnh người dùng đi đâu.

## 5. Ràng buộc kỹ thuật

- Thứ tự nạp: `theme.js` (đặt theme trước khi vẽ) → `fonts.css` → `theme.css` → các CSS khác. Test yêu cầu hai stylesheet đầu tiên là `fonts.css`, `theme.css`.
- Mỗi lần đổi asset, **đổi chuỗi `?v=` trên mọi `<link>`/`<script>`** sang giá trị mới (ví dụ `?v=20261106-aurora3`) để trình duyệt không dùng bản cũ.
- Test chỉ kiểm tra file có dạng `<script src="/static/...">` (không có `type=` đứng trước `src`). Nếu dùng `type="module"`, hãy viết `<script src="..." type="module">` để test vẫn kiểm được file tồn tại.
- Giữ `color-scheme: dark` / `light` theo theme, và tô màu cho `select option` ở cả hai theme (lần trước chữ trong ô chọn bị ẩn trên nền tối).
- Ảnh trong lưới: `loading="lazy"`, `decoding="async"`, giữ tỉ lệ, có `aspect-ratio` để không nhảy bố cục.
- Không đặt `backdrop-filter` hay `filter: blur()` lên phần tử lặp (thẻ ảnh, ô tranh). Tối đa khoảng 6 bề mặt kính cùng lúc trên màn hình.

## 6. Hướng thiết kế

### Giai đoạn 0: chọn hướng cùng người dùng
Giai đoạn này **chỉ đọc mã và viết đề xuất**: chưa sửa file, chưa mở trình duyệt hay cửa sổ nào lên trước màn hình (người dùng có thể đang bận việc khác). Trình bày **3 hướng** ngắn gọn (mỗi hướng 3–5 dòng, kèm ảnh mockup nếu tạo được), đề xuất 1 hướng, rồi **chờ người dùng chọn**. Nếu người dùng bảo "tự chọn", dùng hướng A.

- **A. Luminous Memory (đề xuất):** ảnh kỷ niệm như những mảnh ánh sáng trôi trong không gian. Nền tối sâu, cực quang sống bằng WebGL đổi màu theo ảnh đang xem, kính kiểu visionOS, chiều sâu 3D thật. Giữ "DNA" tím–hồng–hổ phách–cyan nhưng tinh tế, ít neon hơn bản cũ.
- **B. Gallery Noir:** phong cách bảo tàng/editorial. Nền than chì, chữ tiêu đề serif lớn, đèn rọi (spotlight) đi theo con trỏ, khung tranh thật cho thư viện 49 tranh, chuyển động chậm và sang.
- **C. Daylight Pearl:** lấy giao diện sáng làm chủ đạo. Chất liệu ngọc trai/giấy ánh kim, cực quang pastel, bóng đổ mềm kiểu Apple Photos, 3D nhẹ nhàng.

Hướng nào cũng phải có **cả giao diện tối và sáng** hoàn chỉnh (không chỉ đảo màu).

### Chi tiết cho hướng A (điều chỉnh tương ứng nếu chọn B hoặc C)

**Nền và khung**
- Nền WebGL: trường nhiễu cực quang 3–4 màu, trôi chậm, phản ứng nhẹ theo con trỏ; màu lấy từ ảnh bìa bộ ảnh đang mở hoặc ảnh đang xem (trích màu chủ đạo bằng canvas từ thumbnail cùng nguồn). Có bản dự phòng bằng CSS gradient.
- Sidebar thành "dock" kính, thu gọn được; topbar nổi; logo LumaNest vẽ lại (SVG, có bản chuyển động nhẹ, giữ tên file `lumanest.svg`/`lumanest.ico`).
- Chuyển trang bằng **View Transitions API** (`document.startViewTransition`), có dự phòng fade khi trình duyệt không hỗ trợ.

**Bộ ảnh:** hero "chòm sao kỷ niệm": ảnh bìa các bộ xếp trong không gian 3D (CSS 3D hoặc WebGL), kéo/xoay được, hover nổi lên. Bên dưới là bento grid. Số ảnh đếm chạy khi xuất hiện.

**Ảnh (thư viện):** masonry giữ tỉ lệ; thẻ xuất hiện theo cuộn (CSS scroll-driven animations `animation-timeline: view()`, dự phòng IntersectionObserver); hover có nghiêng 3D + đốm sáng đuổi theo con trỏ (một listener ủy quyền + `requestAnimationFrame`, không gắn listener cho từng thẻ); thumbnail mờ rồi nét dần; thanh chọn nhiều ảnh dạng dock nổi; bộ lọc dạng chip có chuyển động.

**Lightbox:** ảnh "bay" từ thumbnail ra (shared-element View Transition); nền ambilight lan màu ảnh; zoom/pan mượt, vuốt trên điện thoại; dải filmstrip; so sánh trước/sau.

**Tìm khuôn mặt:** HUD quét mặt có điểm mốc chuyển động; kết quả hiện lần lượt theo điểm tương đồng, có vòng tròn phần trăm; trạng thái rỗng có minh hoạ.

**Sáng tạo:**
- Sân khấu canvas có ánh đèn và chiều sâu.
- Preset và **49 tranh thành "phòng triển lãm"**: khung tranh, nhãn kiểu bảo tàng (tên, họa sĩ, năm), tab theo 10 nhóm, hover phóng to và đổ bóng.
- Thanh độ đậm dạng nét cọ; tiến độ vẽ hiển thị như **nét cọ vẽ dần** (SVG `stroke-dashoffset` theo phần trăm); khi xong có hiệu ứng lộ ảnh (mặt nạ loang màu).
- So sánh trước/sau bằng thanh kéo; bảng màu dạng swatch nổi 3D; chủ thể: điểm chọn phát sóng, viền mask phát sáng.
- Hàng đợi lô có tiến độ từng ảnh rõ ràng.

**Trợ lý:** nút mở là một **orb 3D** (shader hoặc CSS) "thở" theo trạng thái: chờ, đang nghĩ, đang vẽ. Khung chat kính; tin nhắn hiện dần; thẻ đề xuất phong cách có ảnh xem trước; phần cài đặt nguồn model gọn, rõ ràng.

**Thùng rác:** thẻ mờ dần khi xoá, "bay về" khi khôi phục. **Hệ thống:** thẻ chỉ số có biểu đồ nhỏ, kiểm tra toàn vẹn chạy từng mục với dấu tick chuyển động.

**Chung:** toast, hộp thoại, Ctrl+K dùng spring; nút có hiệu ứng từ tính nhẹ (desktop); con trỏ phát sáng mềm (chỉ desktop, tắt khi giảm chuyển động hoặc màn cảm ứng); skeleton shimmer khi tải; ngôi sao yêu thích bung hạt sáng.

### Hệ thống thiết kế
- **Token** trong `theme.css`: màu ngữ nghĩa, bề mặt, kính, viền, bóng, bo góc, khoảng cách (thang 4px), chữ (dùng `clamp()`), chuyển động (thời lượng + easing spring), độ sâu z-index. Giữ các tên token cũ dưới dạng alias để CSS cũ không gãy.
- **Chữ:** Be Vietnam Pro cho nội dung. Có thể thêm **một** font tiêu đề giấy phép OFL, **bắt buộc hỗ trợ đủ tiếng Việt** (thử các ký tự: Ắ Ặ Ữ Ỹ ơ ư ố ễ). Font tải về để trong `fsmart/static/fonts/` kèm giấy phép.
- **Icon:** một bộ thống nhất dạng SVG sprite cục bộ (Lucide, Phosphor hoặc Tabler).
- **Minh hoạ:** vẽ lại bộ minh hoạ trạng thái rỗng và 4 bước pipeline cho đồng bộ hướng mới (SVG, chuyển động bằng CSS).
- **CSS:** sắp xếp lại bằng `@layer` (tokens, base, layout, components, pages, motion, utilities). Có thể gom 13 file thành ít file hơn, nhưng làm thành **một bước riêng**: commit riêng, chạy test, so ảnh trước/sau không lệch.

### 3D và chuyển động: quy tắc
- 3D phải có ý nghĩa (chiều sâu, tập trung, phản hồi), không chỉ để trang trí. Chữ luôn phẳng và nét.
- Mọi cảnh WebGL: khởi tạo lười khi vào màn hình, **dừng khi tab ẩn**, giải phóng khi rời trang, có bản 2D dự phòng khi không có WebGL.
- Chỉ animate `transform` và `opacity` (và uniform của shader). Không animate `width/height/top/left/box-shadow` trên phần tử lặp.

## 7. Danh sách phải làm lại (kiểm từng mục)

Sidebar/dock · topbar/breadcrumb · nút sáng/tối · bảng lệnh Ctrl+K · màn Bộ ảnh + hộp thoại tạo bộ · lưới ảnh + bộ lọc + tìm kiếm · trình xem ảnh (lightbox) · thanh chọn nhiều · lớp phủ kéo-thả · Tìm khuôn mặt (tải ảnh, chọn mặt, ngưỡng, kết quả) · Sáng tạo (ảnh trong bộ, tab Nghệ thuật/Màu ảnh/Chủ thể, preset, Style của bạn, 49 tranh, độ đậm, tốc độ, nút tạo, trước/sau, chủ thể, bảng màu, lô, lịch sử) · khung trợ lý + cài đặt Qwen/Gemini/API tương thích · Thùng rác · Hệ thống · bảng tác vụ/tiến độ · toast · hộp xác nhận · mọi trạng thái rỗng, đang tải, lỗi · bố cục điện thoại.

## 8. Nguồn tham khảo

**Chỉ để lấy ý tưởng** (không chép mã, ảnh, video hay font của họ):
- Awwwards (awwwards.com, mục Sites of the Day/WebGL), Godly (godly.website), Codrops (tympanus.net/codrops).
- Apple Photos, visionOS Human Interface Guidelines (chất liệu kính, chiều sâu), Material 3 Expressive (chuyển động, hình khối).
- Linear, Raycast, Arc, Stripe (gradient mesh), Vercel: micro-interaction và chữ.
- Hugging Face Spaces: cách các demo AI trình bày trạng thái chạy mô hình, tiến độ, so sánh trước/sau.
- Shadertoy: chỉ xem ý tưởng. Mã trên đó mặc định CC BY-NC-SA, **không chép**.

**Thư viện được phép dùng nếu cần** (vendor về máy, ghi vào `THIRD_PARTY.md`, **tự kiểm tra lại giấy phép khi tải**):
- OGL (github.com/oframe/ogl): WebGL rất nhẹ, hợp cho nền shader.
- three.js (MIT): khi cần cảnh 3D đầy đủ; chỉ nạp ở trang dùng tới.
- Motion (motion.dev, MIT): animation/spring cho JS thuần.
- Icon: Lucide (ISC), Phosphor (MIT), Tabler Icons (MIT).
- Font: chỉ OFL, có tiếng Việt.

**Tạo tài nguyên bằng AI (tuỳ chọn):** nếu cần texture/minh hoạ, chỉ dùng mô hình có giấy phép cho phép, ví dụ FLUX.1 [schnell] (Apache-2.0) trên Hugging Face; ghi tên mô hình, prompt, giấy phép vào `THIRD_PARTY.md`; không tạo ảnh người thật.

## 9. Ngân sách hiệu năng

- Tải trang đầu (DOMContentLoaded, dữ liệu mẫu): ≤ 400 ms. Bản hiện tại khoảng 212 ms.
- JS tự viết thêm ≤ 120 KB chưa nén; thư viện bên thứ ba ≤ 200 KB chưa nén tổng cộng, **chỉ nạp khi cần**. Tổng `fsmart/static/` tăng không quá 3 MB.
- Cuộn lưới 300 ảnh và nền shader: ổn định 55–60 fps trên GPU tích hợp. Shader giới hạn devicePixelRatio ≤ 1.5, có thể chạy 30 fps khi không thao tác.
- Không có tương tác thì CPU/GPU gần như nghỉ: dừng mọi vòng `requestAnimationFrame` không cần thiết.
- Tự hạ cấp hiệu ứng khi: `prefers-reduced-motion`, `navigator.connection.saveData`, không có WebGL, hoặc đo được dưới 40 fps trong 2 giây.
- Thẻ ngoài màn hình dùng `content-visibility: auto`. Thư viện vài nghìn ảnh vẫn phải mượt.

## 10. Truy cập và chất lượng

- Tương phản WCAG AA ở **cả hai theme**: chữ thường ≥ 4.5:1, chữ lớn và thành phần giao diện ≥ 3:1, kể cả chữ đặt trên ảnh và trên kính.
- `:focus-visible` rõ ràng; dùng được hoàn toàn bằng bàn phím; thứ tự tab hợp lý; hộp thoại giữ focus bên trong.
- `prefers-reduced-motion: reduce`: tắt shader động, parallax, nghiêng 3D, hạt; chỉ giữ fade ngắn.
- Vùng bấm ≥ 44px trên cảm ứng. Hoạt động tốt ở 375px, 768px, 1440px và màn rất rộng.
- Mọi trạng thái nhìn rõ khác biệt: hover, active, disabled, `.active`, `.selected`, `.is-favorite`, `.has-selection`, `[aria-pressed="true"]`, `[aria-selected="true"]`, `.hidden`.
- Không có lỗi trong console, không có request lỗi trong tab Network.

## 11. Lỗi lần trước, không được lặp lại

1. Nhiều chỗ chữ không đủ tương phản (23 chỗ ở theme tối, 17 chỗ ở theme sáng phải sửa lại).
2. Hơn 200 lớp `backdrop-filter` khi thư viện có 100 ảnh, gây giật.
3. Thanh tiến độ và các tab công cụ hiển thị sai sau khi đổi CSS.
4. Chữ trong `<select>`/`<option>` bị ẩn trên nền tối.
5. Trình duyệt vẫn hiện giao diện cũ vì không đổi `?v=` của asset.
6. Bố cục điện thoại 375px bị tràn, thanh trên cùng xuống nhiều dòng.

## 12. Các giai đoạn

0. **Khảo sát và chọn hướng:** đọc mã giao diện, trình bày 3 hướng, **dừng lại chờ người dùng chọn**. Ngay sau khi có hướng (trước khi sửa file), chạy app mẫu và chụp ảnh **trước khi sửa** (mỗi trang, tối/sáng, 1440px và 375px).
1. **Hệ thống thiết kế:** token, chữ, icon, thang chuyển động, sắp xếp CSS bằng `@layer`.
2. **Khung ứng dụng:** nền WebGL, dock, topbar, chuyển trang, Ctrl+K, toast, hộp thoại.
3. **Từng trang:** Bộ ảnh → Ảnh + lightbox → Tìm khuôn mặt → Sáng tạo (cả 49 tranh) → Trợ lý → Thùng rác → Hệ thống.
4. **Chuyển động và 3D:** hoàn thiện micro-interaction, cảnh 3D, View Transitions, hạ cấp hiệu ứng tự động.
5. **Kiểm tra chất lượng:** test, tương phản, bàn phím, điện thoại, hiệu năng, gói phát hành (mục 13).
6. **Báo cáo** (mục 14).

Sau mỗi giai đoạn: chạy test, chụp nhanh màn hình, commit.

## 13. Kiểm tra trước khi báo xong

```powershell
cd D:\prjdpl-ui-v3
$env:FSM_WEIGHTS_DIR = 'D:\prjdpl\weights'
# Toàn bộ test (khoảng 2–3 phút), phải 100% pass
D:\prjdpl\.venv\Scripts\python.exe -m pytest -q --basetemp=.cache/pytest-local
# Cú pháp các file JS thường (không phải module)
Get-ChildItem fsmart\static\*.js | ForEach-Object { node --check $_.FullName }
# Gói phát hành phải lấy đủ mọi file trong fsmart/static (kết quả phải là "MISSING: none")
D:\prjdpl\.venv\Scripts\python.exe -c "import sys,pathlib; sys.path.insert(0,'scripts'); import package_release as p; inc={x.relative_to(p.ROOT).as_posix() for x in p.source_files()}; miss=[f.as_posix() for f in pathlib.Path('fsmart/static').rglob('*') if f.is_file() and f.as_posix() not in inc]; print('MISSING:', miss or 'none')"
```

- **Không chạy** `scripts\package_release.py` để build thật: nó ghi đè gói phát hành 1.1.0 và `SHA256SUMS.txt` mà người dùng đang chuẩn bị gửi đi.
- Trong trình duyệt: đi hết các trang và hộp thoại ở cả hai theme, 1440px và 375px; bật "Reduce motion" của Windows và xem lại; xem console và Network.
- Ghi lại số đo: thời gian tải trang, fps khi cuộn, dung lượng JS/CSS thêm vào.

## 14. Báo cáo khi xong

Tạo `docs/ui/ANTIGRAVITY_REPORT_V3.md` gồm:
- Hướng đã chọn và ý tưởng chính.
- Danh sách file đã thêm/sửa/xoá, mỗi file một dòng mô tả.
- Thư viện, font, icon, tài nguyên bên thứ ba: phiên bản, nguồn, giấy phép (đồng thời ghi vào `THIRD_PARTY.md`).
- Kết quả kiểm tra: số test pass, tương phản, bàn phím, điện thoại, các số đo hiệu năng ở mục 9.
- Ảnh chụp **trước/sau** của từng trang (tối/sáng, 1440px/375px) lưu trong `docs/ui/v3/`, JPG ≤ 300 KB mỗi ảnh, chỉ dùng dữ liệu mẫu.
- Những gì chưa xong, còn băn khoăn, hoặc cần sửa backend (ghi rõ để Claude làm).
