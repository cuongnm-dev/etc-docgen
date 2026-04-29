# Dự toán chi phí phần mềm

**Căn cứ:** TT 04/2020/TT-BTTTT, sửa đổi bởi TT 12/2020/TT-BTTTT
**Version:** tt04-2020
**IMMUTABLE — Không sửa cấu trúc outline. Chỉ fill {{content:X.Y}}.**

---

## 1. Căn cứ lập dự toán

<!-- Pháp lý: TT 04/2020, Điều 3 -->
<!-- Hướng dẫn: Pháp lý + cơ sở kỹ thuật. Độ dài: 2-3 trang -->
<!-- SNIPPET: reference/snippets/can-cu-phap-ly/dau-tu-cntt.md -->

### 1.1. Căn cứ pháp lý

{{content:1.1}}

### 1.2. Căn cứ kỹ thuật

{{content:1.2}}

<!-- TKCS/TKCT đã phê duyệt, danh mục chức năng -->

---

## 2. Phương pháp xác định chi phí

<!-- Pháp lý: TT 04/2020, Điều 4-5 -->
<!-- Hướng dẫn: Giải thích phương pháp FP. Độ dài: 2-3 trang -->
<!-- SNIPPET: reference/snippets/phuong-phap-tinh-chi-phi/tt04-2020.md -->

### 2.1. Phương pháp tính

{{content:2.1}}

<!-- Chọn phương pháp phù hợp với dự án:
- **Function Point (TT 04/2020 Phụ lục I-III):** Dùng khi dự án xây dựng phần mềm mới, xác định được chức năng rõ ràng. ĐÂY LÀ PHƯƠNG PHÁP CHÍNH.
- **Phương pháp tương tự (Analogy):** Dùng khi có dự án tương tự đã triển khai, chi phí thực tế đã biết. Phải có bằng chứng hợp đồng tương tự.
- **Phương pháp chuyên gia (Expert):** Dùng khi phạm vi quá mới, không có dự án tương tự, không đủ dữ liệu FP. Cần ít nhất 3 chuyên gia độc lập ký xác nhận.
Nếu dùng nhiều phương pháp → lấy trung bình có trọng số. Ghi rõ lý do chọn phương pháp. -->

### 2.2. Các hệ số áp dụng

{{content:2.2}}

<!-- Bảng hệ số áp dụng:
| Hệ số | Ý nghĩa | Phạm vi | Giá trị áp dụng |
|-------|---------|---------|-----------------|
| K₁ | Ngôn ngữ lập trình | 1,0 – 1,4 | [CẦN BỔ SUNG] |
| K₂ | 14 yếu tố phức tạp | 0,65 – 1,35 | [CẦN BỔ SUNG: tính theo Phụ lục II TT 04] |
| K₃ | Đặc thù dự án | 0,5 – 2,0 | [CẦN BỔ SUNG] |
K₁: Java/C# = 1,0; Python = 1,1; PHP = 1,0; NodeJS = 1,1 (tra Phụ lục I TT 04/2020, sửa đổi bởi TT 12/2020)
K₂: Tính từ 14 yếu tố, mỗi yếu tố 0-5 điểm. K₂ = 0,65 + 0,01 × Σ(điểm)
K₃: Phần mềm thông thường = 1,0; đặc thù BCA/BQP/... = 1,5-2,0 -->

### 2.3. Đơn giá nhân công

{{content:2.3}}

<!-- [VERIFY TRƯỚC KHI DÙNG] Đơn giá nhân công thay đổi hàng năm theo quyết định của Bộ LĐTBXH.
Nguồn tham chiếu: Quyết định về mức lương tối thiểu vùng hiện hành (tra web trước khi lập dự toán).
Vùng I (Hà Nội, HCM): cao nhất. Vùng IV (nông thôn): thấp nhất.
Bảng: Chức danh | Bậc | Đơn giá (đồng/tháng) | Vùng áp dụng | Nguồn -->

---

## 3. Phân tích điểm chức năng (Function Point)

<!-- Pháp lý: TT 04/2020, Phụ lục I-III -->
<!-- Hướng dẫn: Phần lõi dự toán. Độ dài: 10-20 trang -->

### 3.1. Danh mục chức năng

{{content:3.1}}

<!-- Bảng: STT | Module | Chức năng | Mô tả | Loại FP | Độ phức tạp | FP -->

### 3.2. Bảng tính điểm chức năng chi tiết

{{content:3.2}}

<!-- 5 loại FP: EI, EO, EQ, ILF, EIF -->
<!-- Bảng: Chức năng | EI | EO | EQ | ILF | EIF | DET | RET/FTR | Phức tạp | FP -->

### 3.3. Tổng hợp điểm chức năng

{{content:3.3}}

<!-- Bảng tổng: Module | FP thô | Hệ số điều chỉnh | FP điều chỉnh -->

---

## 4. Chi phí xây dựng phát triển phần mềm (G_NC)

<!-- Pháp lý: TT 04/2020, Điều 5 -->
<!-- Hướng dẫn: Áp dụng công thức. Độ dài: 3-5 trang -->

### 4.1. Bảng tính chi phí theo module

{{content:4.1}}

<!-- Bảng: Module | FP | K_1 | K_2 | K_3 | D | Thành tiền -->

### 4.2. Tổng chi phí xây dựng

{{content:4.2}}

---

## 5. Chi phí chỉnh sửa, chuyển đổi phần mềm (G_CDPM)

<!-- Pháp lý: TT 04/2020, Điều 6 -->
<!-- Hướng dẫn: Nếu có. Độ dài: 1-2 trang -->

{{content:5}}

<!-- Nếu không có: ghi "Dự án không phát sinh chi phí chỉnh sửa, chuyển đổi phần mềm." -->

---

## 6. Chi phí khác

<!-- Pháp lý: TT 04/2020, Điều 7-11 -->
<!-- Hướng dẫn: Các khoản chi phí bổ sung. Độ dài: 2-3 trang -->

### 6.1. Chi phí quản lý dự án

{{content:6.1}}

<!-- 5-10% G_NC -->

### 6.2. Chi phí tư vấn

{{content:6.2}}

### 6.3. Chi phí đào tạo, chuyển giao

{{content:6.3}}

### 6.4. Chi phí bảo hành

{{content:6.4}}

### 6.5. Chi phí hạ tầng, thiết bị

{{content:6.5}}

<!-- Nếu dự toán gộp cả phần cứng -->

### 6.6. Dự phòng

{{content:6.6}}

<!-- ≤ 10% tổng -->

---

## 7. Tổng hợp dự toán

<!-- Hướng dẫn: Bảng tổng hợp cuối cùng. Độ dài: 1-2 trang -->

### 7.1. Bảng tổng hợp chi phí

{{content:7.1}}

<!-- Bảng:
| STT | Nội dung | Thành tiền (đồng) | Ghi chú |
| I   | Chi phí PM (G_NC)           | xxx | |
| II  | Chi phí chỉnh sửa (G_CDPM) | xxx | |
| III | Chi phí QLDA                | xxx | 7% × I |
| IV  | Chi phí tư vấn              | xxx | |
| V   | Chi phí đào tạo             | xxx | |
| VI  | Chi phí bảo hành            | xxx | |
| VII | Chi phí hạ tầng             | xxx | |
| VIII| Dự phòng                    | xxx | 10% × (I-VII) |
|     | TỔNG CỘNG                  | XXX | |
| (Bằng chữ: ... đồng) |
-->

### 7.2. Nguồn vốn

{{content:7.2}}

---

## Phụ lục

{{optional:phu-luc}}

<!-- Danh mục phụ lục:
- Phụ lục A: Bảng phân tích điểm chức năng chi tiết
- Phụ lục B: Bảng hệ số K_2 (14 yếu tố)
- Phụ lục C: Đơn giá nhân công tham chiếu
-->
