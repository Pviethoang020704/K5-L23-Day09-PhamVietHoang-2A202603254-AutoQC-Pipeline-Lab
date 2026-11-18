"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
import math

from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    settings = cfg["second_opinion"]
    issues = []
    for image_path in ds.image_files():
        stem = image_path.stem
        if stem not in preds:
            continue

        raw_labels = ds.read_label_lines(stem)
        if raw_labels is None:
            continue

        labels = []
        for line_number, text in raw_labels:
            try:
                box = parse_yolo_line(text)
            except (ValueError, OverflowError):
                continue
            if 0 <= box[0] < len(ds.classes):
                labels.append((box[0], *box[1:], line_number))

        image_size = ds.image_size(stem)
        image_width, image_height = image_size if image_size is not None else (0, 0)

        model_predictions = []
        for index, row in enumerate(preds[stem]):
            if len(row) != 6:
                raise ValueError(
                    f"prediction {index} for {stem!r} must have 6 values"
                )
            try:
                raw_class_id, raw_confidence, *raw_box = row
                class_value = float(raw_class_id)
                confidence = float(raw_confidence)
                box_values = tuple(float(value) for value in raw_box)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"prediction {index} for {stem!r} contains non-numeric values"
                ) from exc

            if (
                not math.isfinite(class_value)
                or not class_value.is_integer()
                or not math.isfinite(confidence)
                or any(not math.isfinite(value) for value in box_values)
            ):
                raise ValueError(f"prediction {index} for {stem!r} contains invalid values")
            if not 0 <= confidence <= 1:
                raise ValueError(
                    f"prediction {index} for {stem!r} has confidence outside [0, 1]"
                )

            class_id = int(class_value)
            cx, cy, width, height = box_values
            if not 0 <= class_id < len(ds.classes) or width <= 0 or height <= 0:
                continue
            model_predictions.append((class_id, confidence, (cx, cy, width, height)))

        checked_predictions = []
        for class_id, confidence, box in model_predictions:
            if confidence >= settings["conf"] and image_size is not None and (
                box[2] * image_width * box[3] * image_height
                >= settings["min_area_px"]
            ):
                checked_predictions.append((class_id, confidence, box))

        for class_id, confidence, box in checked_predictions:
            overlaps = []
            for label_class, cx, cy, width, height, _ in labels:
                overlaps.append(
                    (label_class, iou_xywh(box, (cx, cy, width, height)))
                )
            candidates = [
                (label_class, overlap)
                for label_class, overlap in overlaps
                if overlap >= settings["iou_missing"]
            ]

            if not candidates:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_MISSING",
                        stem,
                        "mô hình phát hiện vật thể nhưng không có nhãn khớp; cần người kiểm tra",
                        extra={"conf": confidence},
                    )
                )
                continue

            same_class = [
                overlap for label_class, overlap in candidates if label_class == class_id
            ]
            if same_class:
                best_iou = max(same_class)
                if best_iou < settings["iou_loose"]:
                    issues.append(
                        Issue(
                            "second_opinion",
                            WARN,
                            "POSSIBLE_LOOSE_BOX",
                            stem,
                            "nhãn cùng lớp có thể bị lỏng hoặc lệch; cần người kiểm tra",
                            extra={"conf": confidence, "iou": best_iou},
                        )
                    )
                continue

            best_other_iou = max(overlap for _, overlap in candidates)
            if best_other_iou >= settings["iou_match"]:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_WRONG_CLASS",
                        stem,
                        "vị trí khớp nhưng lớp nhãn khác dự đoán; cần người kiểm tra",
                        extra={"conf": confidence, "iou": best_other_iou},
                    )
                )

        false_positive_predictions = [
            (class_id, confidence, box)
            for class_id, confidence, box in model_predictions
            if confidence >= settings["fp_conf"]
        ]
        for label_class, cx, cy, width, height, line_number in labels:
            label_box = (cx, cy, width, height)
            best_iou = max(
                (
                    iou_xywh(label_box, prediction_box)
                    for _, _, prediction_box in false_positive_predictions
                ),
                default=0.0,
            )
            if best_iou < settings["iou_missing"]:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_FALSE_POS",
                        stem,
                        "nhãn không khớp dự đoán đủ tin cậy; cần người kiểm tra",
                        line=line_number,
                        extra={"iou": best_iou},
                    )
                )

    return issues
