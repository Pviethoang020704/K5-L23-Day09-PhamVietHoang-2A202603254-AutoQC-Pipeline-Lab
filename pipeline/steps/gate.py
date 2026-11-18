"""BƯỚC 4 — Cửa chặn: quyết định Release / Hold / Rework.   ★

Test:  pytest tests/test_gate.py -q

Cây quyết định Day 07 (slide Day 09: "Lỗi bắt buộc chặn pipeline; lỗi cảnh báo chuyển người xem"):

  còn ≥ 1 lỗi bắt buộc (severity ERROR)                          -> "Rework"
  không còn lỗi bắt buộc, nhưng tỉ lệ ẢNH còn cảnh báo
      >= cfg["gate"]["warn_ratio_hold"]                          -> "Hold"
  còn lại                                                        -> "Release"

Tỉ lệ cảnh báo = (số ẢNH khác nhau có ≥ 1 cảnh báo) / (tổng số ảnh).  Chú ý:
- chỉ đếm issue có `image` nằm trong `image_stems` (bỏ "<dataset>", "data.yaml");
- bỏ qua ảnh nằm trong `reviewed` (người đã xem, cảnh báo của ảnh đó coi như đã xử lý) — nhưng LỖI BẮT BUỘC thì không bao giờ được bỏ qua;
- mẫu số là số ảnh, không phải số issue.

Trả về dict: decision, n_errors, n_warn_images, n_images, warn_ratio (làm tròn 4 chữ số), reasons (list[str], giải thích bằng tiếng Việt, có số liệu).
"""
import math
from numbers import Real

from ..common import ERROR, WARN  # noqa: F401


def decide(issues, image_stems, cfg, reviewed=frozenset()):
    threshold = cfg["gate"]["warn_ratio_hold"]
    if isinstance(threshold, bool) or not isinstance(threshold, Real):
        raise TypeError("gate.warn_ratio_hold phải là một số")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("gate.warn_ratio_hold phải nằm trong khoảng [0, 1]")

    if isinstance(image_stems, (str, bytes)):
        raise TypeError("image_stems phải là tập hợp tên ảnh, không phải chuỗi")
    if isinstance(reviewed, (str, bytes)):
        raise TypeError("reviewed phải là tập hợp tên ảnh, không phải chuỗi")

    images = set(image_stems)
    reviewed_images = set(reviewed)
    if any(not isinstance(stem, str) for stem in images | reviewed_images):
        raise TypeError("tên ảnh trong image_stems và reviewed phải là chuỗi")

    n_errors = 0
    warning_images = set()
    for issue in issues:
        if issue.severity == ERROR:
            n_errors += 1
        elif issue.severity == WARN:
            if issue.image in images and issue.image not in reviewed_images:
                warning_images.add(issue.image)
        else:
            raise ValueError(f"severity không hợp lệ: {issue.severity!r}")

    n_images = len(images)
    n_warn_images = len(warning_images)
    raw_warn_ratio = n_warn_images / n_images if n_images else 0.0
    warn_ratio = round(raw_warn_ratio, 4)

    if n_errors:
        decision = "Rework"
        reasons = [f"Còn {n_errors} lỗi bắt buộc (ERROR); cần xử lý trước khi phát hành."]
    elif raw_warn_ratio >= threshold:
        decision = "Hold"
        reasons = [
            f"Cảnh báo chưa xử lý ở {n_warn_images}/{n_images} ảnh "
            f"({raw_warn_ratio:.4f}), đạt hoặc vượt ngưỡng Hold {threshold:.4f}."
        ]
    else:
        decision = "Release"
        reasons = [
            f"Không còn lỗi bắt buộc; cảnh báo chưa xử lý ở {n_warn_images}/{n_images} ảnh "
            f"({raw_warn_ratio:.4f}), thấp hơn ngưỡng Hold {threshold:.4f}."
        ]

    return {
        "decision": decision,
        "n_errors": n_errors,
        "n_warn_images": n_warn_images,
        "n_images": n_images,
        "warn_ratio": warn_ratio,
        "reasons": reasons,
    }
