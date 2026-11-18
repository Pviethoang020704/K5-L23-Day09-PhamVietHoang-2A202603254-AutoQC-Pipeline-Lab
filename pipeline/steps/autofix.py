"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

from pathlib import Path

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    remove_codes = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}

    drop_lines = defaultdict(set)
    clip_lines = defaultdict(set)
    remove_images = set()
    needs_label = set()
    rename_classes = False

    for issue in issues:
        if issue.severity != ERROR:
            continue
        if issue.code == "BAD_CLASS_NAME":
            rename_classes = True
        elif issue.code == "MISSING_LABEL_FILE":
            needs_label.add(issue.image)
        elif issue.code in remove_codes or issue.code.startswith("DUP_IMAGE_"):
            remove_images.add(issue.image)
        elif issue.code in drop_codes:
            if isinstance(issue.line, int) and issue.line > 0:
                drop_lines[issue.image].add(issue.line)
        elif issue.code == "BOX_OUT_OF_IMAGE":
            if isinstance(issue.line, int) and issue.line > 0:
                clip_lines[issue.image].add(issue.line)

    fixes = []
    removed = set()
    for stem in sorted(remove_images):
        image_path = ds.image_path(stem)
        label_path = ds.label_path(stem)
        paths = [path for path in (image_path, label_path) if path is not None and path.is_file()]
        if not paths:
            continue
        before = ", ".join(path.name for path in paths)
        for path in paths:
            path.unlink()
        fixes.append(
            {
                "image": stem,
                "line": None,
                "action": "remove_image",
                "before": before,
                "after": "đã xóa ảnh và nhãn khỏi ds",
            }
        )
        removed.add(stem)

    for stem in sorted(set(drop_lines) | set(clip_lines)):
        if stem in removed:
            continue
        label_path = ds.label_path(stem)
        if not label_path.is_file():
            continue

        raw_lines = label_path.read_bytes().splitlines(keepends=True)
        changed_lines = []
        changed = False
        for line_number, raw_line in enumerate(raw_lines, 1):
            ending = b""
            body = raw_line
            if body.endswith(b"\r\n"):
                body, ending = body[:-2], b"\r\n"
            elif body.endswith((b"\n", b"\r")):
                body, ending = body[:-1], body[-1:]

            if line_number in drop_lines[stem]:
                fixes.append(
                    {
                        "image": stem,
                        "line": line_number,
                        "action": "drop_line",
                        "before": body.decode("utf-8", errors="replace"),
                        "after": "",
                    }
                )
                changed = True
                continue

            if line_number in clip_lines[stem]:
                original = body.decode("utf-8", errors="replace")
                try:
                    class_id, cx, cy, width, height = parse_yolo_line(original)
                except (ValueError, OverflowError):
                    changed_lines.append(raw_line)
                    continue

                if width <= 0 or height <= 0:
                    intersection = None
                else:
                    left = max(0.0, cx - width / 2)
                    top = max(0.0, cy - height / 2)
                    right = min(1.0, cx + width / 2)
                    bottom = min(1.0, cy + height / 2)
                    intersection = (left, top, right, bottom)

                if (
                    intersection is None
                    or intersection[2] <= intersection[0]
                    or intersection[3] <= intersection[1]
                ):
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_number,
                            "action": "drop_line",
                            "before": original,
                            "after": "",
                        }
                    )
                    changed = True
                    continue

                left, top, right, bottom = intersection
                clipped = (
                    f"{class_id} "
                    f"{(left + right) / 2:.12g} "
                    f"{(top + bottom) / 2:.12g} "
                    f"{right - left:.12g} "
                    f"{bottom - top:.12g}"
                )
                fixes.append(
                    {
                        "image": stem,
                        "line": line_number,
                        "action": "clip_box",
                        "before": original,
                        "after": clipped,
                    }
                )
                changed_lines.append(clipped.encode("utf-8") + ending)
                changed = True
                continue

            changed_lines.append(raw_line)

        if changed:
            label_path.write_bytes(b"".join(changed_lines))

    for stem in sorted(needs_label - removed):
        if ds.image_path(stem) is None or ds.label_path(stem).exists():
            continue
        fixes.append(
            {
                "image": stem,
                "line": None,
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán",
            }
        )

    if rename_classes:
        yaml_path = Path(ds.yaml_path)
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError(f"{yaml_path} phải chứa một YAML mapping")
        else:
            data = {}

        classes = list(cfg["classes"])
        expected_names = dict(enumerate(classes))
        current_names = data.get("names")
        if current_names != classes and current_names != expected_names:
            before = (
                yaml.safe_dump(current_names, allow_unicode=True, sort_keys=False).strip()
                if "names" in data
                else "(không có names)"
            )
            data["names"] = expected_names
            yaml_path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            after = yaml.safe_dump(expected_names, allow_unicode=True, sort_keys=False).strip()
            fixes.append(
                {
                    "image": "data.yaml",
                    "line": None,
                    "action": "rename_classes",
                    "before": before,
                    "after": after,
                }
            )

    return fixes
