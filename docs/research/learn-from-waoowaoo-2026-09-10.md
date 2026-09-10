# Học từ waoowaoo: những gì đáng mang về ArcReel (2026-09-10)

Nguồn: trao đổi trực tiếp với agent của repo `waoowaoo` (v0.5.0-beta.1, `~/Documents/5.GITHUB/waoowaoo`) và đọc các file họ chỉ. waoowaoo là một agent Codex duy nhất làm việc qua 6 SKILL.md + strict JSON + MCP, không có pipeline staged. Tri thức nằm trong prose tiếng Trung của skill, không nằm trong code.

Kết luận ngắn: ArcReel mạnh hơn ở pipeline có cấu trúc, storyboard grid, narration TTS và QA ảnh. waoowaoo mạnh hơn ở **chất lượng prompt rules**, **kỷ luật liên tục giữa các cảnh/tập**, **quote-approve-freeze trước khi tiêu tiền**, và **failure governance**. Phần đáng lấy nhất là prompt rules, chi phí thấp, hiệu quả ngay.

## 1. Chép thẳng vào prompt builders (ưu tiên cao, chi phí thấp)

Nguồn: `src/lib/creative-skills/skills/{asset-development,video-direction,creative-core,script-development}/SKILL.md`.

### 1.1 Character sheet (`lib/prompt_builders_asset*.py`)
- **Neo danh tính bắt buộc**: màu da, màu tóc, màu mắt phải viết rõ. Không viết thì model random mỗi lần (asset-development dòng 44). Ngoài ra: giới/tuổi cảm nhận, hình dáng mặt, ngũ quan, tóc (màu/dài/kiểu/chất), vóc dáng/silhouette, trang phục (kiểu/niên đại/chất liệu/màu), **giày bắt buộc**, phụ kiện chỉ khi tăng nhận diện.
- **Cấm** trong mô tả ổn định: biểu cảm, tư thế, hành động, bối cảnh, đạo cụ đang cầm, từ bất định ("hoặc", "có thể"), tính từ trừu tượng ("khí chất mạnh mẽ") — phải dịch thành silhouette/trang phục/chất liệu nhìn thấy được.
- **Reference board**: 1 ảnh 4:3 chia đôi, trái cận mặt, phải toàn thân không che, nền trắng thuần, không nhân vật/đạo cụ/môi trường khác. Gửi nguyên board vào image-to-video, không crop; chống hiểu nhầm bằng prompt (`@Image N` + một mục đích duy nhất).
- **Trạng thái thay đổi = asset version mới** (bị thương, đổi đồ, cạo đầu), không sửa asset gốc. Asset chỉ khóa danh tính, không phải snapshot trạng thái.
- Non-human: mô tả từ loài/hình thái/bề mặt, không ép khuôn người.

### 1.2 Scene và prop sheet
- Scene: cụ thể hóa tên chung ("khu vườn") thành không gian ổn định; viết tường/sàn/trần/ranh giới/scale; **≥3 điểm neo không gian có chỗ trống quanh để nhân vật đứng sau này**; không vẽ nhãn/mũi tên/placeholder.
- Prop: chỉ thông tin thị giác tĩnh (kết cấu, silhouette, chất liệu, màu, độ mòn); không công dụng, không tay/bàn/phòng, không góc máy/ánh sáng.

### 1.3 Storyboard và video prompt (`lib/prompt_builders_storyboard*.py`, `lib/prompt_builders_video*.py`)
- **Bảng trạng thái nội bộ mỗi shot** (video-direction dòng 31-41): nhân vật (vị trí, hướng thân, ánh nhìn, trang phục, trạng thái cơ thể), đạo cụ (ai cầm, mở/đóng), bối cảnh (giờ, ánh sáng, thời tiết), thông tin đã lộ, âm thanh đang kéo dài. **Entry shot sau = exit shot trước + biến đổi mới.** Shot chỉ tiến, không diễn lại cùng hành động khi đổi cỡ cảnh.
- `[入口状态]`/`[出口状态]`: segment không đầu phải khai entry state, không cuối phải khai exit state; khớp từng mục.
- **Ref chỉ khóa danh tính**, không kế thừa bố cục chính diện/pose/nhìn thẳng ống kính/ánh sáng của asset board (dòng 47). Mỗi ref khai đúng một mục đích.
- **3 câu ràng buộc cố định** (dòng 117-119), dịch sang ngôn ngữ prompt của project:
  1. Ánh nhìn nhân vật rơi vào đối tượng trong cảnh, không giao ống kính.
  2. Cấm dissolve/fade giữa các shot, hình trước-sau không chồng trong suốt.
  3. Không sinh phụ đề, tiêu đề, watermark, collage, chia màn hình, nhân vật thừa.
- **Kỷ luật diễn xuất** (dòng 56-61): cấm tính từ cảm xúc; dịch cảm xúc thành hơi thở/tay/hàm/vai/dáng đi/độ dừng ánh nhìn; biên độ thấp vì model video hay diễn quá; phản ứng phân tầng đông cứng → xác nhận → giải phóng, mỗi shot một tầng, tối đa một lần đổi cảm xúc do sự kiện thấy được trong shot.
- Thoại: `Tên (≤3 từ chất giọng): {lời thoại nguyên văn}`; người nói phải trong khung hoặc rõ nguồn off-screen; câu phải nói xong trước khi block kết thúc. Âm thanh: chỉ viết âm đang nghe được, không BGM.
- Chuyển cảnh: cùng không-thời gian thì cắt thẳng; chỉ dùng transition vật lý khi nhảy thời gian/bước ngoặt.

### 1.4 Script (`lib/prompt_builders_script.py`)
- **Nhịp "đoạt chú ý"** cho drama dọc: ~2 s có xáo trộn đầu tiên, ~6 s hook thành hình, sau đó mỗi 8-10 s một thay đổi THẬT (câu hỏi/đe dọa/chiến thuật/quan hệ/giá phải trả). Không phải 8-10 s mỗi shot. Timeline "trước dày, giữa thưa, cuối dày lại", cấm chia đều. Không quá 2 nhịp thoại thuần liên tiếp.
- **Test che tên**: che tên nhân vật vẫn đoán được ai nói nhờ giọng điệu/từ vựng/chiến thuật.
- Mở đầu là được chọn, không phải sự kiện đầu theo thời gian; cấm mở bằng thiết lập bối cảnh/tự giới thiệu/đi đường/chào hỏi. Mở đầu hứa gì phần chính phải trả tương đương.
- Kết thúc để khán giả "có việc làm"; giáo dục kết bằng insight then chốt; không xin like/follow.
- Mỗi câu thoại làm 2 việc (bề mặt + subtext); im lặng là hành động có chức năng.
- **Không có variant thiếu nhi/giáo dục**: ArcReel phải tự viết "gear" cho khán giả 6-10 (đã có bản nháp trong overview project Bible story, cần đưa vào builder).

### 1.5 Nối tập (creative-core "续作状态锚定", dòng 27-35)
- Trước khi viết tập N+1: đọc lại source text bao trùm điểm nối + exit state của batch giao gần nhất; **cấm tưởng tượng lại từ asset, ấn tượng hay tóm tắt**. Trạng thái biến đổi (trang phục, vết thương, vật cầm) lấy cốt truyện hiện tại làm chuẩn, override asset.
- Viết entry state tường minh vào kết quả mới để downstream không phụ thuộc trí nhớ hội thoại.
- Áp dụng cho nhánh `feat/script-plan-previous-episode-bridge`: ngoài outline tập trước, nên truyền cả **exit state cảnh cuối** (từ storyboard/video prompt cuối) thay vì chỉ hook/teaser.

## 2. Pattern kiến trúc: nên port mảnh nhỏ, không port nguyên khối

| Pattern | waoowaoo | ArcReel hiện tại | Đề xuất | Độ khó |
|---|---|---|---|---|
| Quote → approve → freeze → execute | Plan snapshot hash SHA-256, `ApprovalGrant` single-use (version bump + consumedExecutionId trong transaction), giá per_second theo resolution, model + tham số + aspect ratio đóng băng lúc báo giá | Admission trả batch + `confirmed_request_durations`, không có giá, không snapshot | Port 2 mảnh: (a) **báo giá ước tính trước khi chạy** từ catalog giá per_second (đã có số trong báo cáo chi phí); (b) **đóng băng model + tham số vào batch** lúc admission để config đổi sau không ảnh hưởng batch cũ | Vừa |
| Failure governance | FailureRecord v2 giữ bằng chứng gốc; registry đóng tập quyết định replay theo operation; `outcome_unknown` cấm auto-resubmit; không fallback model, không sửa prompt | Task error + user re-submit | Port nguyên tắc **`outcome_unknown`**: audit mọi chỗ submit provider, timeout/disconnect không được tự resubmit (chỉ poll/cancel được retry). Adapter phải đọc `failReason` có cấu trúc (Seedance copyright reject hiện đang lộ đúng, giữ vậy) | Vừa |
| Resource versioned + lineage | Mọi output là resource có version, lineage input→output ghi cùng transaction, canvas chỉ projection | Artifact có `basis` hash để phát hiện stale | Chưa cần lineage graph đầy đủ; giữ tinh thần "UI chỉ là projection". Cân nhắc lineage hẹp cho video/audio nếu cần truy "clip này sinh từ ref nào" | Thấp → vừa |
| Durable execution (Temporal + attempt ledger) | Có | Worker multiprocessing + file lock | Không port. Deadlock flock đang có (roadmap §5.2) cần sửa theo cách của ArcReel | Cao |
| Stable voice qua `reference_audio` | Tạo 1 mẫu giọng/nhân vật, đo duration bằng ffprobe trước khi báo giá, đưa vào video model khi nhân vật nói ≥2 shot | Chỉ narration TTS | Thử nghiệm nhỏ với Seedance qua Ark: capability `maxReferenceAudios`, min 1.8 s, phải kèm ảnh ref. Không có dữ liệu drift; phải tự đo | Vừa |

Bài học chi phí đáng nhớ: mẫu giọng 1.728 s qua được báo giá rồi bị provider từ chối, user phải trả tiền làm lại → **đo duration thật bằng ffprobe trước khi cho vào plan**, đừng tin số tự khai.

## 3. Những gì họ đã thử rồi bỏ (đừng lặp lại)

- **Node Storyboard/Panel/VideoGroup trên canvas**: bỏ vì "có bản ghi text" bị hiểu là "ảnh đã xong". Xác nhận quyết định roadmap §1: không làm node canvas.
- **Server-side prompt compiler** (server đoán asset type, ghép prompt, adapter append genre/mood sau khi freeze): prompt 1021 ký tự thành 1147 và bị từ chối. Chỉ một tầng được viết prompt; các tầng khác chỉ validate. ArcReel hiện có nhiều tầng chạm prompt (builder, style block, provider adapter) — cần kiểm tra không tầng nào append sau khi user đã xem preview.
- **Auto fallback provider khi hết quota**: bỏ, user bị tính tiền model khác model đã chọn.
- **Sub-agent riêng cho từng chuyên môn** (biên kịch, đạo diễn): bỏ, một agent đọc lần lượt skill.
- **Whitelist tên lỗi/HTTP status để quyết retry**: bỏ, thay bằng hợp đồng idempotent theo operation.
- **BGM pipeline nhiều giai đoạn**: bỏ vì mỗi giai đoạn tự diễn giải một phần trạng thái.
- **Hai bản catalog giá (TS + JSON mirror)**: lệch nhau mà script vẫn báo OK; giữ một nguồn.
- **Dùng `-shortest`/EOF/timer để biết ffmpeg xong**: 99% treo; deadline suy từ duration media. Liên quan trực tiếp script stitch của ArcReel.
- **Chính sách "an toàn người thật" inject thường trực**: hóa cứng giới hạn provider thành chính sách sản phẩm; bỏ khi model hỗ trợ.

## 4. Kế hoạch đưa vào fork (đề xuất thứ tự)

1. **Nhánh `feat/prompt-rules-from-waoo`** (1-2 ngày): đưa §1.1-1.3 vào asset/storyboard/video builders dưới dạng block quy tắc có test snapshot; thêm 3 câu ràng buộc cố định; ref-locks-identity-only. Đo lại bằng Codex QA trên Bible story (so điểm asset/style trước-sau).
2. **Mở rộng nhánh `feat/script-plan-previous-episode-bridge`**: thêm exit state cảnh cuối tập trước vào prompt; sửa Codex P1 (screenplay/reference_video chỉ nối bằng hình).
3. **Nhánh `feat/script-rhythm-and-audience-gear`**: nhịp 2/6/8-10 s, test che tên, gear thiếu nhi 6-10 (ArcReel tự viết, waoowaoo không có).
4. **Nhánh `feat/batch-cost-estimate`**: báo giá ước tính per_second trước khi confirm batch + đóng băng model/tham số vào batch.
5. **Audit `outcome_unknown`** ở các video/image backend submit path; ticket riêng.
6. Thử nghiệm stable voice (reference_audio) trên 2-3 shot Seedance, đo drift bằng Codex/tai người.

Tài liệu kiến trúc nên đọc trước khi port bất kỳ pattern nào: `waoowaoo/docs/architecture/modules/*.md`, mục "踩过的坑" ở cuối mỗi file.
