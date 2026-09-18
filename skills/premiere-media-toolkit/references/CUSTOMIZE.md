# Tuỳ biến skill theo từng người

Skill này ban đầu viết cho workflow của một người. Để người khác dùng được mà
không phải sửa code, mọi thứ mang tính cá nhân đều nằm trong `config.json`.

## Cách bắt đầu

```bash
cp config.example.json config.json
```

Sửa `config.json`, xoá field nào không cần — thiếu field thì skill dùng mặc định.
`config.json` KHÔNG nằm trong file `.skill` chia sẻ, nên mỗi người giữ bản riêng
và nâng cấp skill không mất cấu hình.

Skill tự tìm config theo thứ tự: `--config <path>` → `./config.json` →
`<thư mục skill>/config.json`. Không có thì chạy với mặc định.

## Các nhóm cấu hình

### `user`

| Field | Mặc định | Ý nghĩa |
|---|---|---|
| `name` | rỗng | Tên để skill gọi bạn trong báo cáo. |
| `reply_language` | `vi` | `vi` / `en` / `auto`. `auto` = trả lời theo ngôn ngữ bạn đang viết. |

Bản gốc skill hardcode trả lời tiếng Việt. Nếu bạn làm việc bằng tiếng Anh,
đặt `"reply_language": "en"`.

### `project_structure`

Tên thư mục để skill tự tìm khi bạn chỉ đưa tên project.

| Field | Mặc định |
|---|---|
| `source_dir_names` | `["Source", "Sources"]` |
| `editing_dir_names` | `["Editing File", "Project", "Editing"]` |

Nếu team bạn đặt tên khác (`Footage/`, `02_Source/`, `Premiere/`), thêm vào đây.
Xét theo thứ tự, không phân biệt hoa thường.

### `role_detection` — tự nhận diện nguồn/đích

```json
{ "role_detection": { "b_markers": ["samx"], "a_markers": [], "announce": true } }
```

Path chứa bất kỳ chuỗi trong `b_markers` = thư mục **ĐÍCH**; path còn lại = **NGUỒN**.
Nhờ vậy bạn gửi hai thư mục theo thứ tự nào cũng được, không phải ghi chú cái nào là gì.

- Mặc định `["samx"]` theo quy ước `SAMX_WORKSPACE` của team gốc. Workspace chuẩn
  của bạn tên khác thì đổi chuỗi này.
- `a_markers` để rỗng thì path không khớp `b_markers` tự là nguồn. Điền khi cả
  hai bên đều có dấu hiệu riêng và bạn muốn chắc chắn hai chiều.
- `announce: true` (khuyến nghị) — luôn in `A = ... / B = ...` trước khi chạy.

**Skill từ chối đoán trong 3 trường hợp**: cả hai path đều khớp `b_markers` · không
path nào khớp marker nào · một path khớp cả `a_markers` lẫn `b_markers`. Lúc đó
dùng `--a-root`/`--b-root` để chỉ định thẳng (luôn thắng auto-detect).

Lý do khắt khe: nhận diện sai vai là **copy ngược chiều** — ghi dữ liệu cũ đè lên
thư mục đã organize. Thà hỏi thêm một câu.

### `guards` — chặn ghi vào source chuẩn (bật sẵn)

```json
{ "guards": { "enabled": true, "protect_markers": ["samx"],
              "protect_subdirs": ["Sources", "Source"],
              "output_dirs": ["Asset", "Output"], "protect_paths": [] } }
```

Chặn **mọi** thao tác ghi vào source chuẩn của workspace — copy đè, đổi tên tại
chỗ, rollback. Áp dụng cho tất cả script và **không lách được** bằng `--apply`
hay `--overwrite`, vì guard kiểm theo đường dẫn chứ không theo ý định của script.

Bảo vệ cái gì: thư mục trong `protect_subdirs` nằm **tối đa 2 cấp** dưới gốc
project của workspace có marker. Tức `SAMX_WORKSPACE/<project>/Sources/...` bị
chặn, còn `SAMX_WORKSPACE/<project>/Asset/other/Source/...` thì không — vì nằm
trong `output_dirs`, đó là đích copy hợp lệ của chính skill.

Script đổi tên **tại chỗ** (luồng rename đang đóng băng) bị chặn ngay ở bước
kiểm tham số, kể cả khi chỉ chạy dry-run — để không ai xem kế hoạch rồi
`--apply` theo quán tính.

`apply_copy.py` kiểm **toàn bộ** danh sách đích trước khi ghi byte đầu tiên, nên
không có chuyện copy được một nửa rồi mới dừng.

Thoát guard bằng `"enabled": false` — đừng làm. Nếu thấy bị chặn oan thì sửa
`output_dirs` hoặc đổi đích, đừng tắt guard.

### `behavior`

| Field | Mặc định | Khi nào đổi |
|---|---|---|
| `dedupe_by_default` | `true` | `false` nếu source nằm trên ổ cứng local nhanh và bạn muốn bỏ bước hash. Trên Google Drive nên để `true` vì nó tiết kiệm rất nhiều upload. |
| `forceful_pname` | `true` | `false` nếu bạn hay đổi tên clip trong Premiere để đánh dấu và muốn giữ nhãn đó. |
| `drive_role` | `content_manager` | `contributor` nếu bạn ghi được nhưng không xoá được — skill sẽ tự thêm `--no-delete-dest` để không để lại file `.part` rác. |
| `confirm_before_write` | `true` | `false` nếu bạn muốn skill tự apply sau khi dry-run sạch. Chỉ nên dùng khi đã chạy quen project đó. |

### `structure` — giữ nguyên cấu trúc (thay cho cơ chế bucket cũ)

```json
{ "structure": { "sweep_non_video": true, "non_video_dest": "Asset",
                 "extra_video_dest": "Asset/shared",
                 "external_dest": "Asset/shared" } }
```

Skill **không phân loại lại** resource. Thư mục con của nguồn được giữ nguyên
tên và nguyên cấu trúc khi sang đích.

`sweep_non_video: true` nghĩa là quét **nguyên folder**, lấy cả file mà project
hiện không dùng tới — vì khi chuyển nhà thì chuyển cả kho, không chỉ những gì
đang online.

> Phiên bản trước có `buckets.rules` để đoán thư mục đích theo tên. Đã bỏ hẳn:
> nó xếp `VO - MH` và `VO - SV` vào `Music` vì không khớp chuỗi nào, và kiểu sai
> này rất khó phát hiện. Cấu trúc thư mục của team đã là taxonomy rồi.

### `editing_file`

```json
{ "editing_file": { "copy": true, "dest": "Asset/project/Editing File",
                    "skip_subdirs": ["Adobe Premiere Pro Audio Previews",
                                     "Adobe Premiere Pro Video Previews"] } }
```

Chuyển kèm autosave, fills/masks, voice, composer — bỏ cache Premiere tự sinh
lại được. Thêm tên thư mục vào `skip_subdirs` nếu muốn bỏ thêm.

### `output_folder`

```json
{ "output_folder": { "copy": false, "dest": "Output" } }
```

Mặc định **không** chuyển thư mục Output: nó không được project tham chiếu, và
cấu trúc hai bên thường lệch nhau (`Facebook` vs `FB`, `Tiktok` không có bên
đích...). Bật `copy: true` khi đã thống nhất được cách map tên thư mục.

### `output`

| Field | Mặc định | Ý nghĩa |
|---|---|---|
| `project_subdir` | `Asset/project` | Nơi đặt file `.prproj`/`.aep` sau relink, tính từ gốc thư mục B. |
| `keep_reports` | `true` | Copy kèm `_*_report.csv` để tra cứu về sau. |

## Cái gì KHÔNG nên đưa vào config

Luồng chuyển nhà không phụ thuộc quy ước đặt tên nào — nó giữ nguyên cấu trúc
thư mục của bạn, nên dùng được ngay không cần sửa gì.

Luồng rename/organize (đổi tên file theo quy tắc) là scope khác và đang đóng
băng, không đi kèm bản này.
