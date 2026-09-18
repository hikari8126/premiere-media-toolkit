# premiere-media-toolkit

Skill cho Claude Code: **chuyển nhà thư mục làm việc dựng video** — chuyển nốt phần còn thiếu sang workspace mới và **relink Premiere / After Effects**
khi file đổi tên hoặc khi cả thư mục làm việc chuyển sang workspace mới.

Sinh ra từ nhu cầu thật: một thư mục dự án được nhân bản sang workspace chuẩn rồi
organize lại theo cấu trúc khác, còn `.prproj` (1 GB) và `.aep` thì vẫn trỏ về
đường dẫn cũ.

## Cài

```
/plugin marketplace add hikari8126/premiere-media-toolkit
/plugin install premiere-media-toolkit
```

Cập nhật về sau: `/plugin update premiere-media-toolkit`

## Làm được gì

| Việc | Script |
|---|---|
| Chuyển nhà A→B khi B đã đổi cấu trúc | `plan_relink_b.py` → `apply_copy.py` → `emit_manifest.py` |
| Đồng bộ `.prproj` theo manifest (đường dẫn + tên hiển thị) | `relink_premiere_v2.py` + `fix_residual_prproj.py` |
| Đồng bộ `.aep` (RIFX binary) | `relink_aep.py` |

Điểm đáng chú ý:

- **Xử lý được `.prproj` cỡ GB** — đọc theo bytes dạng stream, không dùng
  ElementTree (sẽ OOM).
- **Không nhầm khi trùng tên file** — đi theo chuỗi UID
  `MasterClip → Clip → MediaSource → Media` thay vì so basename.
- **Giữ nguyên cấu trúc thư mục**, không tự phân loại lại. Bản cũ từng có cơ chế
  đoán thư mục đích theo tên và nó xếp `VO - MH` vào `Music`; đã bỏ hẳn.
- **Phát hiện file trùng nội dung khác tên** bằng hash đầu/cuối, relink thẳng
  thay vì copy bản thứ hai.
- **Truy vết media offline có thật sự nằm trên timeline không**, bằng đồ thị
  `ObjectUID`/`ObjectURef` — trả lời được "file chết này có ảnh hưởng gì không".

## Guard

Skill **không bao giờ ghi vào source chuẩn của workspace đích**. Guard kiểm theo
đường dẫn nên `--apply`, `--overwrite` hay gọi script khác đều không lách được;
bị chặn thì thoát với exit code 3.

Chặn cả ở chế độ dry-run đối với script đổi tên file **tại chỗ**, vì người ta
hay xem dry-run thấy hợp lý rồi `--apply` theo quán tính.

## Tuỳ biến

```bash
mkdir -p ~/.claude/premiere-media-toolkit
cp skills/premiere-media-toolkit/config.example.json ~/.claude/premiere-media-toolkit/config.json
```

Để config ở đó — **ngoài thư mục plugin** — thì `/plugin update` không xoá mất.

Tuỳ biến được: ngôn ngữ trả lời, tên thư mục theo quy ước của team, marker nhận
diện workspace đích, vùng cấm ghi, đích cho từng loại resource, cache Adobe nào
bỏ qua. Chi tiết trong `skills/premiere-media-toolkit/references/CUSTOMIZE.md`.

## Yêu cầu

Python 3.8+, không cần thư viện ngoài.

## Giấy phép

Nội bộ Crossian.
