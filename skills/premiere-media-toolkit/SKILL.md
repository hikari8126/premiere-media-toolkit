---
name: premiere-media-toolkit
description: CHUYỂN NHÀ thư mục làm việc dựng video — khi một project được nhân bản sang workspace mới rồi organize lại theo cấu trúc khác, skill chuyển nốt phần còn thiếu và relink Premiere (.prproj) + After Effects (.aep) về đường dẫn mới, đồng thời sửa tên hiển thị trong Project panel cho khớp. TỰ KÍCH HOẠT khi user đính kèm 2 thư mục project (một cũ, một mới) — không cần nói rõ việc cần làm. Cũng dùng khi user nói "chuyển nhà", "chuyển project sang workspace mới", "dup A sang B rồi organize lại", "relink theo đường dẫn mới", "media offline sau khi chuyển thư mục", "footage offline trong AE", "đổi tên hiển thị clip theo file mới". Xử lý được .prproj cỡ GB, trùng tên file, file trùng nội dung khác tên, và truy vết media offline có nằm trên timeline không.
---


# Premiere Media Toolkit

## Ngôn ngữ phản hồi

Mặc định **trả lời bằng tiếng Việt** (team gốc dùng skill này là người Việt),
kể cả khi prompt viết bằng tiếng Anh. Đổi bằng `config.json`:

```json
{ "user": { "reply_language": "en" } }
```

`vi` = tiếng Việt · `en` = tiếng Anh · `auto` = theo ngôn ngữ user đang viết.

Áp dụng cho mọi message: dry-run report, apply summary, error, câu hỏi xác nhận,
verification checklist. Không đổi ngôn ngữ giữa chừng.

Technical term (tên flag, tên file, tên chunk RIFX, ppath/sname/pname, label UI
của Premiere/After Effects) giữ nguyên không dịch. Chỉ phần văn xuôi viết theo
ngôn ngữ đã chọn.

---

## Kích hoạt

**Thấy 2 thư mục project được đính kèm → hiểu ngay là chuyển nhà.** Không hỏi
"anh muốn làm gì", chỉ cần nhận diện vai rồi chạy dry-run.

| User đưa vào | Skill hiểu là |
|---|---|
| 2 thư mục project | chuyển nhà — thư mục khớp marker (`samx`) là ĐÍCH, cái còn lại là NGUỒN |
| 2 thư mục + `.prproj`/`.aep` | chuyển nhà, relink luôn các project file đó |
| 1 thư mục + `.prproj` | thiếu vế kia — hỏi thư mục còn lại |
| "chuyển nhà <tên project>" | tự dò 2 thư mục theo tên, xác nhận với user trước khi chạy |

Việc đầu tiên luôn là in ra `A = ... / B = ...` rồi dry-run. Không hỏi lại những
gì đã có mặc định (xem "Skill KHÔNG cần hỏi").

## 🛡️ Guard: KHÔNG BAO GIỜ ghi vào source chuẩn của workspace

`<workspace có marker>/<project>/Sources/` là bản source chuẩn dùng chung của
doanh nghiệp. Skill này **chỉ được ĐỌC nó**, dưới mọi hình thức: không copy đè,
không đổi tên, không rollback, không tạo file mới trong đó.

Guard nằm ở `scripts/guard.py`, được nối vào tất cả script có khả năng ghi, và
kiểm **theo đường dẫn** chứ không theo ý định của script — nên `--apply`,
`--overwrite` hay gọi script khác đều không lách được. Bị chặn thì thoát với
exit code **3** và in rõ lý do.

| Script | Guard chặn ở đâu |
|---|---|
| `apply_copy.py` | kiểm TOÀN BỘ đích trước khi ghi byte đầu tiên, + kiểm lại trước từng file |
| `plan_relink_b.py` | từ chối sinh ra kế hoạch có đích nằm trong vùng bảo vệ |
| script đổi tên tại chỗ (luồng cũ, đang đóng băng) | ngay khi kiểm tham số, **kể cả dry-run** |

Phạm vi bảo vệ: thư mục `Sources`/`Source` nằm **tối đa 2 cấp** dưới gốc project
của workspace có marker. `SAMX_WORKSPACE/<project>/Sources/...` bị chặn;
`SAMX_WORKSPACE/<project>/Asset/other/Source/...` KHÔNG bị chặn vì nằm trong
`output_dirs` — đó là đích copy hợp lệ của chính skill.

Cấu hình trong `config.json` → `guards` (xem `references/CUSTOMIZE.md`). Tắt
được bằng `guards.enabled = false` nhưng **đừng tắt**: bị chặn oan thì sửa
`output_dirs` hoặc đổi đích.

Khi guard chặn, ĐỪNG tìm cách đi vòng. Báo user biết path nào bị chặn và hỏi họ
muốn đổi đích thế nào.

## Câu mở đầu chuẩn — DÙNG NGUYÊN VĂN

Khi skill vừa được cài/nạp và user CHƯA đưa thư mục nào, trả lời **đúng khối
dưới đây**, không thêm bớt, không đổi từ, không thêm emoji. Mọi người trong team
phải thấy cùng một câu chào thì mới biết skill đã nạp đúng.

### 1. Vừa cài xong hoặc user vừa import skill

> Skill **chuyển nhà** đã sẵn sàng.
>
> Việc nó làm: chuyển nốt phần còn thiếu của một project sang workspace mới rồi
> relink Premiere (`.prproj`) và After Effects (`.aep`) về đường dẫn mới, đồng
> thời sửa tên hiển thị trong Project panel cho khớp.
>
> Cách dùng: kéo **2 thư mục project** vào ô chat — thư mục cũ và thư mục mới —
> rồi gõ `chuyển nhà`. Không cần nói rõ cái nào là nguồn, cái nào là đích.
>
> Trước khi ghi bất cứ thứ gì, tôi luôn chạy thử và đưa bạn xem báo cáo.

### 2. User đưa đủ 2 thư mục

Không chào hỏi, vào việc luôn. Câu đầu tiên đúng một dòng:

> Đang dựng kế hoạch chuyển nhà.

Rồi in `A = ... / B = ...` và khối `BÁO CÁO CHUYỂN NHÀ`.

### 3. User mới đưa 1 thư mục

> Mới có một thư mục. Cần thư mục còn lại — bản cũ hoặc bản mới đều được, tôi tự
> nhận ra cái nào là đích.

### 4. User hỏi skill làm được gì

Dùng nguyên khối ở mục 1.

### Cấm trong mọi câu mở đầu

Không hứa trước kết quả ("sẽ relink sạch sẽ", "đảm bảo không lỗi") · không đoán
số liệu trước khi chạy · không liệt kê tính năng kỹ thuật (UID chain, RIFX,
hash) trừ khi user hỏi · không emoji · không "Chào bạn!".

## Mẫu trả lời chuẩn — DÁN NGUYÊN VĂN

`plan_relink_b.py` in ra một khối `BÁO CÁO CHUYỂN NHÀ` ở cuối. **Dán nguyên văn
khối đó vào câu trả lời**, trong code block. Không viết lại bằng lời của mình,
không đổi thứ tự, không thêm bớt số liệu.

Lý do: cùng một kết quả thì mọi session phải cho ra cùng câu chữ. User đọc quen
mắt, và so được giữa lần chạy này với lần trước. Model tự diễn giải thì mỗi lần
một kiểu — cùng dữ liệu mà lần thì "khá nhiều file offline", lần thì "hầu hết
đều ổn".

Sau khối báo cáo, Claude chỉ được viết thêm **tối đa 3 câu**, và chỉ để:
- nêu việc cần user quyết mà script không tự biết (quyền ghi, chọn phương án)
- cảnh báo điều script chưa kiểm được
- hỏi xác nhận apply

Cấm: tóm tắt lại con số đã có trong báo cáo · đánh giá kiểu "kết quả rất tốt" ·
thêm emoji · đổi cách gọi tên mục.

### Khi báo cáo ghi "KHÔNG CÓ BẤT THƯỜNG"

Trả lời đúng một câu sau khối báo cáo, nguyên văn:

> Không có gì bất thường. Xác nhận thì tôi chạy apply.

### Khi báo cáo có mục "CẦN LƯU Ý"

Không diễn giải lại từng mục — script đã ghi rõ. Chỉ hỏi đúng những gì cần
quyết, mỗi ý một dòng, không quá 3 dòng.

### Sau khi apply

Dán nguyên văn phần tổng kết của `apply_copy.py` (dòng `xong: copy N, lỗi M...`)
và kết quả verify, rồi dùng checklist ở mục "Verification checklist" — cũng
nguyên văn, không tự chế thêm mục.

## Quy chuẩn gửi file cho skill

Phần lớn thời gian mất vào việc đoán xem thư mục nào là gì. Gửi đúng chuẩn thì
skill chạy được ngay, không phải hỏi lại.

### Nguyên tắc

1. **Gửi ĐƯỜNG DẪN, đừng gửi ảnh chụp Finder.** Skill cần path để đọc file, ảnh
   không dùng được. Trong Claude Code: kéo thư mục từ Finder vào ô chat, hoặc
   gõ `@` rồi chọn. Trên macOS: chọn thư mục → `Cmd+Option+C` để copy path.
2. **Gửi thư mục gốc, đừng gửi file lẻ.** Skill cần quét cả cây để dựng index.
   Đưa `project thật/` chứ đừng đưa 5 file `.mov` bên trong.
3. **Vai nguồn/đích thường tự nhận diện được.** Path chứa marker trong
   `config.role_detection.b_markers` (mặc định: `samx`) là **ĐÍCH (B)**, path
   còn lại là **NGUỒN (A)** — gửi hai thư mục theo thứ tự nào cũng được, không
   cần ghi chú. Skill luôn in rõ `A = ... / B = ...` trước khi chạy để bạn kịp
   chặn nếu sai. Khi cả hai path đều khớp (hoặc không path nào khớp), skill
   **hỏi lại chứ không đoán** — nhận diện sai là copy ngược chiều.
4. **Nói trước nếu thư mục read-only.** Tiết kiệm cả tiếng đồng hồ so với việc
   phát hiện lúc đang copy.

### Cần gửi gì cho từng luồng

| Luồng | Bắt buộc | Nên có |
|---|---|---|
| **Chuyển nhà** | 2 thư mục project | file `.prproj`, `.aep`, quyền ghi ở đích |

### Mẫu tin nhắn dùng luôn được

```
Thư mục 1: <kéo vào đây>
Thư mục 2: <kéo vào đây>
Project: <kéo file .prproj>
AE: <kéo file .aep, bỏ trống nếu không có>
Quyền ở đích: ghi được / read-only / ghi được nhưng không xoá được
Đặt file relink ở: <đường dẫn, hoặc "tự chọn">
```

Không cần ghi cái nào là nguồn/đích — path chứa `samx` (hoặc marker bạn cấu
hình) tự được nhận là đích. Chỉ ghi rõ khi cả hai path đều có marker, hoặc khi
bạn muốn đảo vai so với mặc định.

### Skill PHẢI hỏi lại nếu thiếu

Đừng đoán khi chưa có: **quyền ghi ở đích**. Đây là câu duy nhất còn phải hỏi
trước khi chạy.

Các mặc định đã chốt, KHÔNG hỏi lại:
- Luôn **copy**, không bao giờ move/xoá ở nguồn.
- File đã có bản trùng nội dung trong đích → **relink thẳng**, không copy bản thứ hai.
- File relink mới luôn đặt trong workspace đích (`Asset/project`).
- Asset của project khác → `Asset/shared`, giữ nguyên đường dẫn.

Vai nguồn/đích thì tự nhận diện (xem nguyên tắc 3) — nhưng nếu nhận diện mơ hồ
thì PHẢI hỏi, tuyệt đối không chọn bừa.

### Skill KHÔNG cần hỏi

Tự chạy dry-run, tự đọc `config.json`, tự dựng index, tự đếm và báo cáo. Chỉ
chặn lại ở đúng bước ghi/copy đầu tiên.

## Tuỳ biến theo từng người

Mọi thứ mang tính cá nhân nằm trong `config.json` (ngôn ngữ trả lời, tên thư mục
theo quy ước của team, mapping bucket, có dedupe hay không, role trên Drive, nơi
đặt file output). Bắt đầu bằng:

```bash
cp config.example.json config.json
```

Đọc `references/CUSTOMIZE.md` để biết từng field. Thiếu field thì dùng mặc định;
không có `config.json` thì skill chạy như cũ.

**Đầu mỗi session, ĐỌC `config.json` nếu có** và tuân theo:
- `user.reply_language` — ngôn ngữ trả lời (ghi đè mục "Ngôn ngữ phản hồi" bên trên)
- `behavior.drive_role: "contributor"` — tự thêm `--no-delete-dest` khi chạy `apply_copy.py`
- `behavior.confirm_before_write: false` — được phép apply ngay sau dry-run sạch
- `behavior.forceful_pname: false` — KHÔNG ghi đè tên hiển thị user tự đặt
- `output.project_subdir` — nơi đặt file sau relink
- `structure` — đích cho từng loại resource, và có quét nguyên folder hay không
- `editing_file` — chuyển kèm Editing File, bỏ cache Adobe nào
- `output_folder.copy` — mặc định `false`, không chuyển thư mục Output
- `guards` — vùng cấm ghi. Bật sẵn, bảo vệ source chuẩn của workspace. Xem mục
  Guard bên trên.
- `role_detection.b_markers` — dấu hiệu nhận ra thư mục ĐÍCH từ đường dẫn.
  Mặc định `["samx"]` theo quy ước `SAMX_WORKSPACE` của team gốc. Đổi theo
  workspace chuẩn của bạn, hoặc thêm `a_markers` nếu nguồn cũng có dấu hiệu
  riêng.

## Concepts (terminology dùng nhất quán)

- **sname** = tên file media trên Finder (basename, vd `Y1.MOV`).
- **spath** = đường dẫn đầy đủ file trên Finder (vd `/.../Source/Fiverr/Mia/Y1.MOV`).
- **pname** = tên hiển thị trong Premiere Project panel (lưu trong `<Title>`, `<Name>` của MasterClip, `<Name>` của ClipProjectItem).
- **ppath** = đường dẫn file source trong .prproj (lưu trong `<FilePath>`, `<ActualMediaFilePath>`, `<RelativePath>`).
- **manifest CSV** = bảng `old_relative_path,new_relative_path` ghi lại mọi thay đổi rename. File này là cầu nối giữa organize và relink.

Mục tiêu chung: khi sname/spath thay đổi (do organize), pname/ppath cũng thay đổi tương ứng (do relink).

## Các script

Luồng chuyển nhà chạy theo thứ tự này:

```
plan_relink_b.py  →  apply_copy.py  →  emit_manifest.py
                  →  relink_premiere_v2.py  →  fix_residual_prproj.py
                  →  relink_aep.py
```

`build_move_manifest.py` là công cụ phụ, chỉ để so hai cây thư mục trước khi
quyết định gì.

> **Luồng cũ (organize/rename + rollback + rebase) đang ĐÓNG BĂNG.**
> Đó là scope khác: đổi tên file trong Source rồi relink theo manifest rename.
> KHÔNG đi kèm bản này. Cần dùng lại thì lấy từ bản lưu nội bộ.

### 1. plan_relink_b.py — Dựng kế hoạch chuyển nhà

Tình huống: project được nhân bản từ A sang B rồi **organize lại theo cấu trúc
mới** — đổi tên folder, gom/chia lại category, có khi đổi cả tên file. Khớp theo
đường dẫn tuyệt đối là vô dụng.

Script này khớp path theo **basename → loose key → longest path suffix → size**,
bỏ qua prefix hoàn toàn. Bắt buộc dùng khi .prproj có nhiều biến thể prefix do
project đã bị di chuyển nhiều lần.

Phân loại mỗi tham chiếu thành 4 nhóm và sinh 2 file:
- `copy_plan.csv` — file cần copy vào B, kèm bucket đích trong `B/Asset/`
- `relink_map.csv` — bản đồ `old_path → new_path` + status từng entry

Status: `IN_B` (đã có trong B, trỏ thẳng) · `IN_B:DEDUPE` (B đã có bản trùng nội
dung, khác tên) · `COPY:<bucket>` (cần copy) · `DEAD` (file không tồn tại ở bất
kỳ đâu → offline vĩnh viễn) · `SKIP_CACHE` (.cfa/.pek).

Usage:
```
# tự nhận diện vai theo config.role_detection (thứ tự bất kỳ):
python3 scripts/plan_relink_b.py \
  --root <ProjectFolder 1> --root <ProjectFolder 2> \
  --prproj <project.prproj> [--aep <project.aep>] \
  [--dedupe] [--outdir <dir>]
```

Chỉ định thẳng khi cần đảo vai hoặc khi nhận diện mơ hồ:
`--a-root <NGUỒN> --b-root <ĐÍCH>` (luôn thắng auto-detect).

`--dedupe` hash 1MB đầu + 1MB cuối mỗi file, nếu B đã có bản trùng nội dung thì
relink thẳng vào B thay vì copy bản thứ hai. Với Google Drive, pha này chậm (phải
tải nội dung về) — chạy nền, khoảng 5 phút cho 700 file.

**Nguyên tắc đích: GIỮ NGUYÊN CẤU TRÚC, không phân loại lại.**

| Loại | Đích |
|---|---|
| Không phải video (BGM, SFX, Image, VO, Licenses, Overlay...) | `Asset/<đường dẫn con giữ nguyên>` |
| Video mà `Sources` của workspace CHƯA có | `Asset/shared/<đường dẫn con giữ nguyên>` |
| File mượn từ project khác | `Asset/shared/<project nguồn>/<tối đa 2 thư mục>/<file>` |
| `Editing File/` (autosave, fills/masks, voice, composer) | `Asset/project/Editing File/<giữ nguyên>` |

⚠️ **Đừng bê nguyên đường dẫn drive vào đích.** File mượn từ project khác nếu
giữ nguyên path từ `Shared drives/` sẽ ra 8-9 cấp mà phần lớn là tên drive và
thư mục vỏ (`Video`, `Editing File`) — không nhận dạng được gì:

```
shared/CPM.Content Storage_Team 01/EaseMotions 2/Video/Editing File/Voice/34x/x.mp3   ← 9 cấp
shared/EaseMotions 2/Voice/34x/x.mp3                                                  ← 5 cấp
```

Giữ tên project nguồn (để biết mượn từ đâu) + tối đa `structure.shared_max_dirs`
thư mục có nghĩa gần file nhất. Thư mục vỏ bị loại: `video(s)`, `source(s)`,
`editing file(s)`, `project(s)`, `output(s)`, `asset(s)`.

**Gộp thư mục cùng nghĩa khác tên** (`BGM` / `BGMs` / `Music`): theo bảng
`structure.merge_aliases.groups` trong config. Mặc định `mode: on_conflict` —
CHỈ gộp khi có từ 2 biến thể cùng tồn tại trong source; chỉ có một thì giữ
nguyên tên gốc, vì đổi `Music` thành `BGM` khi không ai trùng là tự tiện.
Chỉ áp cho thư mục **cấp 1**, không đụng thư mục con.

⚠️ Bảng alias do USER khai, skill KHÔNG tự suy ra nhóm. Suy ra nhóm chính là
cách `VO - MH` từng bị xếp vào `Music`.

Script quét **nguyên folder** chứ không chỉ file được project tham chiếu — team
muốn chuyển cả file hiện không dùng tới. Riêng cache Adobe (`Adobe Premiere Pro
Audio Previews`, `Video Previews`) bị bỏ qua vì Premiere tự sinh lại; với
project thật chúng chiếm 7,9/11,9 GB.

⚠️ **KHÔNG tự nghĩ ra bảng phân loại thư mục.** Skill từng có cơ chế đoán bucket
theo tên thư mục và nó xếp `VO - MH`, `VO - SV`, `Licenses`, `Overlay` vào
`Music` — sai mà rất khó phát hiện. Taxonomy đã nằm sẵn trong tên thư mục của
team; việc của skill là giữ nguyên, không diễn giải lại.

**File project (.aep / .prproj) được tham chiếu:**

Premiere link sang comp After Effects bằng đường dẫn `.aep` (Dynamic Link).
Đường dẫn này PHẢI được relink, nếu không Premiere vẫn mở bản AE cũ ở thư mục
nguồn — sửa gì trong AE mới ở đích cũng không thấy.

| Tham chiếu | Xử lý |
|---|---|
| `.aep`/`.prproj` của CHÍNH project đang xử lý | trỏ sang `<đích>/Asset/project/<tên file>` |
| `.aep`/`.prproj` của project KHÁC | giữ nguyên — ta không relink nó, nó vẫn nằm đúng chỗ |
| `.cfa`, `.pek` | bỏ qua, cache Adobe |

⚠️ **Relink đường dẫn .aep PHẢI dùng `relink_premiere_v2.py --paths-only`.**
Với Dynamic Link, `<Title>` của Media là **tên comp** (`AeriSoft Linked Comp 03/FX.aep`),
không phải tên file. Chế độ forceful mặc định sẽ ghi đè nó thành `FX.aep` và
**mọi comp mất sạch tên** — đã xảy ra thật: 56 comp bị đổi thành cùng một tên.
`--paths-only` chỉ đổi đường dẫn, bỏ qua Title và bỏ qua cả Phase B.

Bản GỐC của file project không bao giờ được copy sang đích — bản đã relink được
ghi riêng vào `Asset/project`. Copy cả hai sẽ để lại một file cũ trỏ về đường
dẫn cũ, và người mở nhầm nó thì không hiểu vì sao media offline.

### 2. apply_copy.py — Thực thi copy_plan.csv

Copy qua file tạm `.part` rồi `os.replace` → ngắt giữa đường không để lại file
nửa vời. Dừng rồi chạy lại được (dest cùng size = skip). KHÔNG ghi đè file khác
size, chỉ báo `CONFLICT`, trừ khi truyền `--overwrite`.

```
python3 scripts/apply_copy.py copy_plan.csv [--apply] [--bucket other] [--overwrite]
```

### 3. emit_manifest.py — relink_map.csv → manifest cho relink script

```
python3 scripts/emit_manifest.py relink_map.csv -o manifest_relink.csv \
  [--exclude "<chuỗi trong old_path>"]
```

Bỏ dòng `DEAD`/`SKIP_CACHE` và dòng chỉ xuất hiện ở `RelativePath`. Dùng
`--exclude` để loại các khớp suy đoán mà user không tin (vd loose key coi khoảng
trắng và dấu chấm là tương đương: `4 2.png` ↔ `4.2.png`).

Manifest sinh ra dùng trực tiếp cho `relink_premiere_v2.py` và `relink_aep.py`
(cả hai khớp theo suffix nên absolute path dùng được), nên **pname tự động đổi
theo tên file ở B** qua UID chain.

### 4. relink_premiere_v2.py — Sync .prproj theo manifest

Sau khi organize, dùng manifest CSV để update .prproj:
- **ppath** (3 tag): `<FilePath>`, `<ActualMediaFilePath>`, `<RelativePath>` — đổi sang đường dẫn mới.
- **pname** (3 chỗ): `<Title>` trong `<Media>` block, `<Name>` trong `<MasterClip>`, `<Name>` trong `<ClipProjectItem>` — đổi sang basename mới.

**Forceful mode** (mặc định): luôn đổi pname thành new_sname, kể cả khi user đã rename thủ công trong Premiere. Mất custom label nhưng giữ nhất quán với Finder.

**Phase B (v5 — UID chain)**: walk topology `MasterClip → Clip → MediaSource → Media` để resolve mỗi clip về đúng 1 Media bất kể basename collision. Trước đây v4 dùng basename matching và skip khi `1.MOV` trùng giữa nhiều folder; v5 không còn skip vì mỗi MC/CPI đã có sẵn ObjectRef chain trỏ đích chính xác.

**Streaming bytes-based** để handle .prproj đến 1GB+ uncompressed (KHÔNG dùng ElementTree để tránh OOM).

Usage:
```
python3 scripts/relink_premiere_v2.py <project.prproj> <manifest.csv> [--apply] [-v]

# CHỈ đổi đường dẫn, không đụng tên hiển thị — dùng cho tham chiếu .aep/.prproj
python3 scripts/relink_premiere_v2.py <project.prproj> <manifest_project.csv> --paths-only --apply
```

Default = dry-run. Output:
- `<project>.RELINKED.prproj` — file đã update.
- `<project>.ORIGINAL.BACKUP.prproj` — backup tự động.
- `<project>.relink_report.csv` — báo cáo từng entry.

### 5. fix_residual_prproj.py — Vá 3 chỗ relink_premiere_v2.py chưa chạm

Chạy SAU `relink_premiere_v2.py --apply`, trên file `.RELINKED.prproj`:

- `<SubClip><Name>` — subclip hiện trong Project panel với tên riêng, KHÔNG đi
  qua UID chain của MasterClip nên script chính bỏ sót.
- `<ClipLoggingInfo><ClipName>` — trường metadata logging, đổi cho nhất quán.
- `<RelativePath>` — tính lại theo vị trí MỚI của file project. ⚠️ Mỗi `<Media>`
  block có **HAI** tag `<RelativePath>` (một trước `<FilePath>`, một trước
  `<ActualMediaFilePath>`) — phải thay CẢ HAI, dùng `sub()` không phải `search()`.

```
python3 scripts/fix_residual_prproj.py <project.RELINKED.prproj> <manifest.csv> \
    --project-dir "<thư mục project SẼ nằm ở>" [--apply]
```

Chỉ đổi khi map tên KHÔNG mơ hồ (1 tên cũ → đúng 1 tên mới); mơ hồ thì báo và bỏ qua.
Output: `<project>.RELINKED.FIXED.prproj`.

### 6. relink_aep.py — Sync .aep (After Effects) theo manifest

After Effects .aep file là RIFX (big-endian RIFF) binary, KHÔNG phải XML như Premiere. Mỗi footage item là một `Item` LIST chunk chứa:
- `Utf8` chunk: basename hiển thị (vd `2.MOV`)
- `LIST` (form=`Pin `) → `LIST` (form=`Als2`) → `alas` chunk: JSON `{"ascendcount_base":N,"ascendcount_target":M,"fullpath":"/abs/path",...}`

Script này:
- Parse RIFX tree recursive, tìm Item LISTs.
- Match `fullpath` trong alas JSON với manifest old paths (suffix match).
- Khi match: thay path mới + recompute `ascendcount_target` cho path-depth delta (vd `Sources/Taobao/1.mp4` → `Sources/Clip/Taobao/c_Taobao 1.mp4` depth +1).
- Update Utf8 chunk content với new basename.
- Rebuild RIFX với chunk sizes recompute tự động.
- Preserve XMP metadata trailer (4-5KB sau RIFX chunk).

Usage:
```
python3 scripts/relink_aep.py <project.aep> <manifest.csv> [--apply] [-v]
```

Output: `<project>.RELINKED.aep` + `<project>.ORIGINAL.BACKUP.aep` + `<project>.aep_relink_report.csv`.

**Khi nào dùng**: sau `relink_premiere_v2.py`, nếu project có cả AE thì chạy thêm `relink_aep.py` cho mỗi file `.aep` cần đồng bộ, dùng CÙNG manifest.

### 7. build_move_manifest.py — Dựng manifest A→B thuần theo cây thư mục

Nhẹ hơn `plan_relink_b.py`: chỉ quét 2 cây thư mục và ghép file, không đọc
project. Dùng khi cần biết A và B lệch nhau thế nào trước khi quyết định gì.
Chỉ đọc `os.stat`, không đọc nội dung → an toàn với Google Drive stub.

```
python3 scripts/build_move_manifest.py <A_root> <B_root> -o manifest.csv [--ext all]
```

## Workflow end-to-end

```
1. plan_relink_b.py --dedupe      → copy_plan.csv + relink_map.csv
2. Đọc report: nhóm DEAD có nằm trên timeline không? (xem mục "Truy vết
   media chết" dưới) → quyết định có cần cứu file từ Drive trash không.
3. Chốt với user 3 điểm: copy hay move · file của project khác xử lý sao ·
   file B đã có bản trùng nội dung thì relink hay copy bản thứ hai.
4. KIỂM TRA QUYỀN GHI ở B trước khi chạy copy (xem pitfall bên dưới).
5. apply_copy.py --apply          → copy vào B/Asset/<bucket>/
6. emit_manifest.py               → manifest_relink.csv
7. relink_premiere_v2.py --apply  → đổi ppath + pname theo B
7b. relink_premiere_v2.py --paths-only --apply  → đổi đường dẫn .aep (Dynamic Link)
8. fix_residual_prproj.py --apply → vá SubClip/ClipName/RelativePath
8. relink_aep.py --apply          → đổi footage path + tên theo B
9. Đặt file .RELINKED vào `Asset/project` của workspace đích, mở verify.
```

## Lệnh gọi

Lệnh chính là **`chuyển nhà`**. Lệnh cũ `relink` đã đổi nghĩa — nó chỉ còn là
một bước bên trong, không phải tên của cả việc.

| Lệnh | Hành vi |
|---|---|
| đính kèm 2 thư mục | tự hiểu là chuyển nhà, chạy dry-run luôn |
| `chuyển nhà <tên project>` | dò 2 thư mục theo tên, xác nhận vai, dry-run |
| `chuyển nhà` (sau khi đã đính kèm) | như trên |
| `apply` | thực thi kế hoạch vừa dry-run trong session |
| `chuyển nhà <project> --apply` | dry-run rồi apply luôn nếu không có entry lỗi |

Người dùng có thể đặt alias riêng — nói "từ giờ gõ X nghĩa là Y" hoặc ghi vào
`CLAUDE.md` của project.

**Tự dò cấu trúc** khi chỉ có tên project:

```
<ProjectName>/
├── Source/ hoặc Sources/        ← media
└── Editing File/ hoặc Project/  ← .prproj + .aep
```

Tên thư mục lấy từ `config.json` → `project_structure`. Không khớp thì hỏi user
chỉ rõ đường dẫn, đừng đoán.

## Workflow trong Cowork / sandbox

Sandbox thường read-only với folder mount. Workflow điều chỉnh:

1. `plan_relink_b.py --outdir <writable_path>` — sinh copy_plan + relink_map ra thư mục ghi được.
2. Copy .prproj từ folder gốc → workspace (writable).
3. `relink_premiere_v2.py <copy.prproj> <manifest.csv> --apply` — output `<copy>.RELINKED.prproj` trong workspace.
4. User download `.RELINKED.prproj` và `manifest.csv` về máy:
   - Chạy `apply_copy.py --apply` thật trên máy (write được).
   - Copy `.RELINKED.prproj` đè file gốc trong Editing File/.
   - Mở Premiere verify.

## Truy vết media chết (media có thật sự dùng không?)

Khi report có nhóm `DEAD`, đừng chỉ đếm số — user luôn hỏi "những file đó có
xuất hiện trong project không?". Trả lời bằng cách đi ngược chuỗi tham chiếu:

1. `<Media>` dùng `ObjectUID="<GUID>"`, KHÔNG phải `ObjectID` số. Nó được trỏ
   tới qua `ObjectURef="<GUID>"`. Muốn dựng đồ thị đầy đủ phải bắt **cả hai**
   loại: `Object(ID|UID)=` cho node và `Object(Ref|URef)=` cho cạnh. Chỉ bắt
   `ObjectID`/`ObjectRef` là không tìm được block Media nào.
2. Dựng map ngược `target → {owner}`: owner của một `ObjectRef` là node có
   `ObjectID`/`ObjectUID` gần nhất PHÍA TRƯỚC nó trong file.
3. BFS từ UID của Media đi lên. Nếu chạm node có tên chứa `TrackItem`
   (`VideoClipTrackItem`/`AudioClipTrackItem`) → media ĐANG nằm trên timeline,
   mở project sẽ thấy Media Offline. Không chạm → chỉ nằm trong Project panel,
   vô hại.

Chi phí: prproj 1GB có ~2,1 triệu object và ~2,3 triệu cạnh, dựng đồ thị + BFS
mất ~10 giây. Rẻ hơn nhiều so với để user tự mở project mò.

## Common pitfalls

### Nhóm pitfall của luồng A→B (v5.3 — học từ job thậtjectX)

- **KIỂM TRA QUYỀN GHI TRƯỚC KHI LÀM BẤT CỨ GÌ**. Shared drive của doanh nghiệp
  có thể read-only toàn bộ, kể cả thư mục `Asset/` mà ta định copy vào. Test
  ngay đầu session, đừng đợi đến lúc chạy copy mới phát hiện (job thật phát
  hiện ở bước cuối sau khi đã dựng xong toàn bộ kế hoạch).
  Cách đọc quyền nhanh: `ls -ld "<Shared drives>/<TênDrive>"` — `drwx` là ghi
  được, `dr-x` là không. Quyền nằm ở **gốc shared drive** (role của tài khoản
  trên drive đó), không phải ở thư mục con, nên test ở gốc là đủ.
- **Role Google Drive quyết định script chạy được kiểu gì**:
  | Role | Thêm file | Sửa | Xoá/rename | Dùng được gì |
  |---|---|---|---|---|
  | Viewer/Commenter | ✗ | ✗ | ✗ | không copy được gì vào |
  | **Contributor** | ✓ | ✓ | **✗** | `apply_copy.py --no-delete-dest` |
  | Content manager | ✓ | ✓ | ✓ | `apply_copy.py` mặc định |
  Với Contributor, cách ghi qua file tạm `.part` rồi `os.replace` SẼ THẤT BẠI
  (cả rename lẫn dọn file tạm đều cần quyền xoá) và để lại rác không xoá được.
  Bắt buộc truyền `--no-delete-dest` để ghi thẳng vào tên cuối.
- **Mount của Drive desktop cache quyền cũ**. Nếu user nói "tôi test thì ghi
  được" mà script báo `Permission denied`, rất có thể quyền vừa được cấp và
  mount chưa nạp lại. Bảo user khởi động lại Drive:
  `osascript -e 'quit app "Google Drive"' && sleep 5 && open -a "Google Drive"`
  rồi kiểm tra lại mode bits. ĐỪNG kết luận user nhầm.
  Nếu B read-only: hoặc xin quyền Content Manager, hoặc relink phần thiếu về
  path ở A (A vẫn đọc được) và chấp nhận project phụ thuộc cả hai thư mục.
- **Khớp lỏng phải TRÙNG ĐÚNG phần mở rộng**, không chỉ cùng lớp media. Chỉ
  kiểm tra "cùng là ảnh" sẽ cho `Frame.png → Frame.psd`, `21.webp → 21.MOV`.
  Loose key bỏ ext để so phần stem, nên phải chặn ext riêng.
- **Đừng đếm `RelativePath` như media riêng**. Mỗi media có cả `<FilePath>`,
  `<ActualMediaFilePath>` và `<RelativePath>`; gộp hết vào một set làm số
  "media chết" phồng lên gấp 4 (job thật: 115 → thực tế 31).
- **Nhiều biến thể prefix trong cùng 1 project**. Project bị di chuyển nhiều
  lần sẽ chứa lẫn lộn: path hiện tại, `/Volumes/Macintosh HD/...`, double slash
  `Team 04//project thật`, path của vị trí cũ, và cả path Windows `G:/Shared drives/...`
  từ máy đồng nghiệp. Phải chuẩn hoá prefix khi kiểm tra tồn tại, và tuyệt đối
  không khớp theo absolute path.
- **File cùng nội dung khác tên**: B có thể đã chứa sẵn file mà ta định copy,
  chỉ khác tên (vd `Clip_1.mp4` = `20260809_..._scene10-1 [id].mp4`). Hash
  1MB đầu + 1MB cuối là đủ để xác nhận. Job thật tiết kiệm 13,45/18,77 GB
  nhờ bước này. Đánh đổi: pname sẽ thành tên ở B (dài, khó đọc) — PHẢI hỏi user
  chứ đừng tự quyết.
- **Đổi tên chỉ khác hoa/thường** (`41.mov` → `41.MOV`) chiếm phần lớn danh
  sách "cần đổi tên". Tách riêng khi báo cáo, đừng để user tưởng có hàng trăm
  file bị rename thật.
- **Google Drive: `os.stat` rẻ, đọc nội dung ĐẮT**. Quét cây thư mục và lấy
  size không kích hoạt download; hash thì có. Mọi bước cần nội dung phải chạy
  nền và báo trước cho user là sẽ lâu.
- **Nhóm asset chưa được copy sang B**: kiểm tra `Asset/` của B có rỗng không
  TRƯỚC khi hứa relink được. B của project thật có 864 video nhưng `Asset/` rỗng
  hoàn toàn → 423 tham chiếu mp3/wav/png không có đích.

- **CANONICAL HOÁ PATH TRƯỚC KHI PHÂN LOẠI**. `os.path.exists` trả True cho
  CẢ `/Volumes/Macintosh HD/Users/...` (mount trỏ về `/`) VÀ path có `//`
  (POSIX coi `//` = `/`). Nếu hàm "tìm file trên đĩa" trả về dạng nguyên văn,
  thì `src.startswith(a_root)` fail → file của chính A bị xếp vào bucket
  `shared` với đường dẫn lồng nhau, và CÙNG MỘT FILE bị copy 2-3 lần vào 2-3
  đích khác nhau (một cho mỗi biến thể prefix trong project).
  Sinh biến thể theo thứ tự canonical-trước: strip `/Volumes/Macintosh HD`
  → gộp `//` → mới đến dạng nguyên văn. Job thật: lỗi này làm copy_plan
  phồng từ 148 lên 645 file và 38 footage AE khớp sai đích.
- **Kiểm tra chéo `new_path` sau khi sinh manifest**: cùng một basename trỏ tới
  >1 đích là bình thường (file khác nhau trùng tên), nhưng cùng một SOURCE FILE
  ra >1 đích thì chắc chắn sai. Grep `dest` xem còn `//`, `Volumes`, hay đoạn
  đường dẫn của drive nguồn bị lồng vào không.

### Giới hạn đã biết của relink_aep.py: footage trong folder

`relink_aep.py` CHỈ xử lý `Item` LIST ở cấp ngoài. Footage nằm trong folder của
AE Project panel có cấu trúc `Item → Sfdr → Item`, và `rewrite_item_list_content`
copy nguyên văn mọi chunk con không phải `Utf8`/`Pin ` → **footage trong folder
bị bỏ qua**. Job thật: 48/87 fullpath được đổi, 39 cái còn lại (VO, SFX nằm
trong folder) vẫn trỏ về A.

Ảnh hưởng: nếu thư mục nguồn cũ vẫn tồn tại thì footage đó VẪN ONLINE (chỉ là
lấy từ chỗ cũ). Nếu nguồn cũ bị xoá thì offline.

⚠️ ĐỪNG vá bằng cách cho `rewrite_item_list_content` đệ quy vào LIST con một
cách ngây thơ. Đã thử: file phình từ 10 MB lên 39,5 MB và số `fullpath` từ 87
lên 608 — nội dung bị nhân bản vì chunk được emit nhiều lần qua cả hai nhánh
(pass 1 no-match và pass 2). Muốn vá đúng thì phải viết lại traversal thành
một lượt duy nhất, có kiểm tra `len(output) == len(input) + tổng delta path`
làm assert, và test trên .aep có folder lồng nhiều cấp trước khi tin.

- **Tên thư mục KHÁC NHAU giữa các project.** `Videos/Source` (project này) vs
  `Video/Sources` (project kia) vs `Source/` ngay ở gốc. Hardcode một kiểu là
  trượt ngay ở project thứ hai. Dò theo `project_structure.source_dir_names` /
  `editing_dir_names`, không phân biệt hoa thường, thử cả trong `Videos/`,
  `Video/` và gốc. Không thấy thì DỪNG và báo user, đừng đoán.
- **RÚT GỌN `..` TRƯỚC KHI GHÉP ĐÍCH.** .prproj chứa path kiểu
  `Voice Over/8x/../../../Sources/Douyin/x.mp4`. Ghép thẳng vào đích sẽ ra
  `Asset/project/Editing File/Voice Over/8x/../../../Sources/...`; hệ điều hành
  tự giải `..` khi copy nên file rơi vào thư mục khác **mà không báo lỗi gì**.
  `os.path.normpath` cho cả path nguồn lẫn đích.

- **ĐỪNG ghi qua file tạm `.part` khi đích là thư mục đồng bộ đám mây.** Google
  Drive theo dõi theo từng thao tác ghi: nó bắt đầu upload ngay file `.part`,
  rồi khi ta đổi tên thành tên thật thì Drive MẤT DẤU — file thật không bao giờ
  được xếp hàng upload, còn `.part` rơi vào lost-and-found. Trên máy thì file
  trông như đã copy xong, `ls` thấy đủ, nhưng đồng nghiệp mở Drive thì KHÔNG
  THẤY GÌ. Đã xảy ra thật: 4 file lớn nhất (3,7 GB) đứng im hơn một ngày.
  `apply_copy.py --part-file auto` (mặc định) tự ghi thẳng khi đích nằm trong
  `/CloudStorage/`, `Google Drive`, `OneDrive`, `Dropbox`.
- **Copy xong KHÔNG có nghĩa là đã upload.** Kiểm bằng xattr:
  `xattr <file> | grep com.google.drivefs.item-id` — có item-id nghĩa là Drive
  đã nhận trên cloud. Trước khi báo "xong" cho user, đếm số file thiếu item-id.
  File kẹt thì ghi lại (xoá rồi copy thẳng) là Drive nhận ngay.

### Pitfall chung

- **OOM trên file lớn**: `relink_premiere_v2.py` MUST dùng streaming bytes (đã built-in). Đừng refactor sang ElementTree — sẽ crash trên .prproj > 500MB.
- **Basename collision** (FIXED ở v5): file ngắn (`1.MOV`, `21.MOV`) trùng tên giữa nhiều sub-folder vẫn rename đúng nhờ UID chain. Trước đây (v4) skip ambiguous, giờ resolve qua `MasterClip → Clip → MediaSource → Media`.
- **MC unresolved chain**: một số MasterClip không link tới Media (vd sequences, nested compositions, audio submix) → script log "MC unresolved chain: N" và skip — đây là bình thường.
- **Forceful overwrites custom labels**: nếu user đã rename clip trong Premiere/AE để đánh dấu, relink sẽ ghi đè. Đó là tradeoff đã chốt.
- **AEP XMP trailer**: `.aep` thường có XMP metadata block sau RIFX chunk. `relink_aep.py` MUST preserve trailer (script đã handle), không được drop. Kiểm tra `len(new) ≈ len(old) + delta(paths/names)` để verify.
- **AEP `ascendcount_target`**: nếu path mới có depth khác path cũ (vd Taobao/x.mp4 → Clip/Taobao/c_Taobao 1.mp4 depth +1), phải update field này trong alas JSON — không thì AE không tìm được file.
- **Empty L1 folder không xóa được trên Google Drive**: organize cố `rmdir` empty subfolders. Google Drive thường chặn. User xóa thủ công. Riêng `Stu/` rỗng từ lần chạy trước được tự động reuse (không tạo `Stu1/`).
- **Studio Stu/ giữ số gốc**: file `Studio/25.MOV` → `Stu/Stu 25.MOV` (bảo toàn số), KHÔNG renumber tuần tự thành `Stu 77.MOV` như v4 cũ. Sequential renumber theo alphabetic string sort (1, 10, 100, 117, 25, ...) gây confusion nên đã bỏ.
- **Description có chữ Trung**: Logic 4 bỏ desc nếu chứa CJK characters. Behavior intended.
- (luồng cũ) **Pre-restructure đè lên Logic 9 idempotency**: nếu chạy organize 2 lần, lần 2 vẫn move các loose B file (vì pre-restructure không check idempotency). Vô hại nhưng có thể warn nếu thấy ops > 0 sau lần đầu --apply.

## Verification checklist

Sau khi relink Premiere, mở `.prproj` và kiểm tra:
- [ ] Không có "Media Offline" trong sequences.
- [ ] Project panel hiển thị sname mới (tên file mới ở workspace đích).
- [ ] File trỏ tới đường dẫn mới (right-click clip → Reveal in Finder).
- [ ] Sequences vẫn play đúng (timing không lệch).
- [ ] Audio/effects vẫn link.

Sau khi relink After Effects, mở `.aep` và kiểm tra:
- [ ] Project panel không có footage offline (không có icon ❓).
- [ ] Tên footage hiển thị đã đổi (tên file mới ở workspace đích).
- [ ] Right-click footage → Reveal in Finder → mở đúng file mới.
- [ ] Comps render preview OK, không lệch timing.

Nếu có offline media/footage:
- Check `<project>.relink_report.csv` (hoặc `.aep_relink_report.csv`) xem manifest entry nào không match.
- Có thể do file thật chưa được rename (organize chưa --apply trên Source thực).
- Hoặc file trong project reference vào folder khác (BGMs, voice over, project khác) — đó là bình thường, không thuộc scope rename.

## Reference files

- `references/CUSTOMIZE.md` — **Đọc trước nếu bạn là người mới dùng skill này.**
  Cách tuỳ biến qua `config.json`: ngôn ngữ, tên thư mục theo quy ước team,
  mapping bucket, dedupe, role Drive, nơi đặt output.
- `config.example.json` — Template config. `cp config.example.json config.json` rồi sửa.

Đọc các file này khi cần tham khảo edge case hoặc giải thích quyết định cho user.
