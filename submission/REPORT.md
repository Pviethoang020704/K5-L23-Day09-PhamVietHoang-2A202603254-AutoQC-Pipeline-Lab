# Báo cáo Day 09 — Chưa cung cấp họ tên/MSHV

## 1. Kết luận trước

Pipeline quét **224 ảnh**, tiếp nhận **193 ảnh** và loại **31 ảnh** (3 ảnh sai kích thước, 2 ảnh hỏng, 8 ảnh trùng byte, 7 ảnh trùng gần và 11 ảnh rò rỉ test/val). QC vòng đầu trên 193 ảnh có **36 lỗi bắt buộc** và **149 cảnh báo**. Sau AutoFix và 80 lượt review mô phỏng, còn **0 lỗi bắt buộc**, nhưng **34/193 ảnh** vẫn có cảnh báo chưa xử lý (**0.1762**); gate kết luận **HOLD**. `clean_v1` được xuất để thử nghiệm, là **bản nháp**, không phải bản Release.

## 2. Lỗi và phân việc

Các số bên dưới là số issue/dòng trong `02_error_list_v1.csv`; một ảnh có thể có nhiều issue. 36 lỗi bắt buộc QC không gồm 31 ảnh bị loại ở intake.

| Mã lỗi | Số issue | Ai xử lý | Vì sao |
|---|---:|---|---|
| `BAD_CLASS_ID` | 6 | Máy | Xóa dòng có class ID ngoài danh sách |
| `BAD_CLASS_NAME` | 2 | Máy | Chuẩn hóa `names` trong `data.yaml` theo cấu hình |
| `BAD_FORMAT` | 3 | Máy | Xóa dòng nhãn sai định dạng |
| `BOX_OUT_OF_IMAGE` | 8 | Máy | Cắt box vào khung; nếu không còn phần giao thì xóa dòng |
| `BOX_ZERO` | 4 | Máy | Xóa box có chiều rộng/cao bằng 0 |
| `DUP_BOX` | 7 | Máy | Xóa dòng box trùng sau |
| `MISSING_LABEL_FILE` | 6 | Người | Máy không tự bịa nhãn; chuyển ảnh cho người gán |
| `BOX_HUGE` | 3 | Người | Cảnh báo cần xem ảnh |
| `BOX_TINY` | 6 | Người | Cảnh báo kích thước box |
| `CLASS_RARE` | 4 | Người | Cảnh báo mất cân bằng lớp |
| `EMPTY_LABEL` | 11 | Người | Cần phân biệt ảnh nền thật với thiếu nhãn |
| `POSSIBLE_FALSE_POS` | 28 | Người | Chỉ là nghi vấn từ model |
| `POSSIBLE_LOOSE_BOX` | 27 | Người | Cần xem box trên ảnh |
| `POSSIBLE_MISSING` | 53 | Người | Model có thể sai; cần xác nhận vật thể |
| `POSSIBLE_WRONG_CLASS` | 17 | Người | Model có thể sai lớp; cần xác nhận |

`01_intake.csv` ghi 31 ảnh bị loại trước QC. `03_fixes.csv` có 35 dòng audit: 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`. Hàng đợi có 121 ảnh và xếp theo điểm ưu tiên giảm dần, cộng trọng số cảnh báo theo loại cùng các fix cần người xem; vì vậy ảnh thiếu nhãn được ưu tiên cao (`NEEDS_LABEL` trọng số 10). Review log ghi 80 ảnh đã xem; 74 ảnh có cờ ngữ nghĩa, tổng cộng 88 cờ (51 missing, 17 wrong class, 12 false positive, 8 loose box; các loại có thể cùng xuất hiện trên một ảnh).

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall / F1 (trước → sau) | Lý do |
|---|---:|---:|---|---|
| `duplicates.phash_dist` — near duplicate | 2 | 16 | `1.00/0.50/0.67` → `1.00/0.83/0.91` | Tăng recall từ 3/6 lên 5/6 lỗi chèn, chưa có FP trong 39 ảnh calib; ngưỡng 20 làm recall giảm và có thể gộp nhầm nhiều hơn. Exact duplicate giữ `1.00/1.00/1.00`. |
| `second_opinion.conf` — wrong class | 0.25 | 0.60 | `0.56/0.83/0.67` → `0.62/0.83/0.71` | Precision/F1 tăng, recall giữ nguyên trong calib. |
| `second_opinion.conf` — missing | 0.25 | 0.60 | `0.50/1.00/0.67` → `0.57/1.00/0.73` | Precision/F1 tăng, recall giữ nguyên trong calib. |
| `second_opinion.conf` — loose box | 0.25 | 0.60 | `0.29/0.40/0.33` → `0.20/0.20/0.20` | Hiệu năng giảm; ngưỡng chung là đánh đổi giữa các loại cảnh báo, không tối ưu riêng cho loose box. |
| `POSSIBLE_FALSE_POS` | 0.25 | 0.60 | `0.31/1.00/0.48` → `0.31/1.00/0.48` | Không đổi vì loại này dùng `fp_conf=0.1`, ngưỡng cố định. |

Calib chỉ có 39 ảnh và ít lỗi chèn ở một số loại nên mỗi ca có thể làm precision/recall thay đổi mạnh; nhãn/model trong calib cũng không đại diện đầy đủ cho lỗi tự nhiên của raw. Trên raw, `phash_dist=16` loại 7 near duplicate, trong đó 3 cặp có khoảng cách đúng 16 (`img_0011`, `img_0084`, `img_0177` với ảnh được nêu trong intake report). Vì đây là các cặp sát ngưỡng và raw không có ground truth cho near duplicate, cần mở ảnh xác minh để đánh giá nguy cơ loại nhầm; số liệu calib không đủ chứng minh mọi cặp raw là trùng thật.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

Trong lần chạy đã lưu, gate thấy **0 lỗi bắt buộc** nhưng **34/193 = 0.1762**, vượt `warn_ratio_hold=0.10`, nên chọn **HOLD**. `08_summary.json` và `clean_v1/manifest.json` cùng ghi quyết định HOLD, 193 ảnh; export này chỉ là bản nháp để thử nghiệm, chưa được phát hành. Muốn đủ điều kiện Release cần giữ 0 lỗi bắt buộc và đưa số ảnh còn cảnh báo chưa xử lý xuống dưới 10% (tối đa 19/193 ảnh). Chưa có log của lần chạy `--budget 0`; vì vậy chưa ghi nhận thực nghiệm Rework/mã thoát 20 hay việc không export trong trường hợp đó.

Điểm mù đã biết: (1) nếu nhãn và checker cùng bỏ sót hoặc cùng nhầm một vật/lớp, phép đối chiếu không nhất thiết phát hiện; mô hình chỉ đưa ý kiến, không phải ground truth. (2) Tài liệu calibration nêu ảnh bị crop mạnh rồi thu nhỏ có thể lọt khỏi phát hiện trùng perceptual-hash. Đây là giới hạn của phương pháp, không phải khẳng định các lỗi đó đã được xác nhận trong raw.

## 5. Train: raw vs clean (tùy chọn)

**CHƯA CHẠY.** `submission/results/` chưa có kết quả train; do đó không báo cáo mAP, Precision hoặc Recall của mô hình.

## 6. Quyết định và ghi chú AI

Quyết định cuối là **HOLD**, không phải Release. Cần xử lý các cảnh báo còn lại bằng review của người và chạy lại gate; chỉ được xem xét Release khi không còn lỗi bắt buộc và tỷ lệ ảnh cảnh báo chưa xử lý thấp hơn 0.10.

- **Prompt chính:** Dùng GitHub Copilot hỗ trợ hoàn thiện các module theo docstring, API và yêu cầu của lab; không sửa tests/configs/dữ liệu gốc ngoài phần được phép.
- **Cách kiểm:** Chạy unit test từng module và toàn bộ `pytest` (**79/79 passed**); đối chiếu calibration, báo cáo CSV/JSON và manifest để xác nhận số liệu pipeline.
- **Lần AI sai:** Chưa có ví dụ sai cụ thể được ghi nhận; không tự tạo ví dụ.

CVAT: không thực hiện.
