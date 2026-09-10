# Roadmap fork ArcReel: dọn nền trước, nâng chất lượng nội dung sau

> Trạng thái: đề xuất, viết ngày 2026-09-09 sau khi chạy trọn hai tập của project `Bible story`
> (drama, storyboard grid, Gemini + Veo 3.1 lite + OpenAI TTS). Bổ sung cho
> `arcreel-vs-zjt-main-drama-shorts-comparison.md`. Số liệu dòng mã lấy tại commit `18409749` (main).

## 1. Quyết định nền tảng

| Câu hỏi | Kết luận | Lý do |
|---|---|---|
| Fork? | Có | Repo gốc là upstream của người khác; ta cần tự do sửa lõi và giữ commit local cho tới khi upstream. |
| Viết lại lõi bằng Go? | Không, ít nhất chưa | 140k dòng backend + 200k dòng test + 18 bước migration + 76 ADR. Mọi lỗi gặp trong hai tập vừa rồi là kỷ luật concurrency và logic nghiệp vụ, không phải giới hạn ngôn ngữ. Tải hệ thống là chờ API provider. Hệ sinh thái AI (google-genai, openai, instructor, pydantic, Claude Agent SDK) mạnh hơn hẳn ở Python. |
| Có chỗ nào đáng dùng Go? | Một dịch vụ media tách riêng, sau này | Ghép ffmpeg, transcode, upload: binary tĩnh, song song rẻ, không đụng logic nghiệp vụ. Chỉ làm khi hiệu năng thật sự thành vấn đề. |
| Node-based canvas như zjt-main? | Không | Mô hình pipeline tuyến tính theo tập của ArcReel đủ cho sản xuất hàng loạt và là chỗ nó vượt zjt-main (admission, basis/stale, batch bền). |

Quy mô hiện tại (không tính node_modules):

| Phần | Dòng | File |
|---|---|---|
| `lib/` | 87.424 | 319 |
| `server/` | 53.074 | 132 |
| `frontend/src/` | 126.897 | 569 |
| `tests/` | 201.614 | 599 |

## 2. Những gì đã thấy khi chạy thật (2 tập, 17 cảnh)

Chi phí thực tế: 9 ảnh tài sản + 19 storyboard (Gemini image), 17 giọng đọc (OpenAI TTS), 22 lần gọi Veo 3.1 lite (8 giây, 0,64 USD/lần, gồm 4 lần gửi lại do Gemini trả rỗng hoặc lỗi nội bộ).

### 2.1 Lỗi chặn (đã sửa, commit local)

| Lỗi | Nhánh / commit | Ghi chú |
|---|---|---|
| Gemini Developer API từ chối `additionalProperties` trong `responseSchema`; `plan_episodes` fail 400 với mọi model Pydantic `extra="forbid"` | `fix/gemini-response-schema-additional-properties` @ `f1c68e3e` | Lược khoá này trong `lib/text_backends/gemini.py::_const_to_enum`. |
| Tập 2 trở đi mở đầu không nối tập trước: script_plan chỉ nhìn lát cắt nguồn của tập, không dùng teaser tập trước / hook tập này | `feat/script-plan-previous-episode-bridge` @ `cc222eff` | `previous_episode_outline_context` trong `lib/episode_ledger.py`; khối `<previous_episode_outline>` + quy tắc mở đầu trong `lib/prompt_builders_script.py` và `lib/prompt_builders_reference.py`; chỉ vào basis khi có tập trước. |

### 2.2 Lỗi đã chẩn đoán, chưa sửa

**Deadlock TTS làm treo cả server** (tái hiện 2 lần, khi từ 2 TTS trở lên commit trong cùng giây)

- Luồng commit TTS (`server/services/generation_tasks.py::execute_tts_task` → `_commit_staged`) chạy trong worker thread, giữ `.project.json.lock` qua `pm.locked_episode_script`, rồi gọi `EventLoopBridge.run(...)` để chờ event loop trả `resolve_tts_synthesis_settings`.
- Trong lúc đó một coroutine khác trên event loop gọi khoá project **đồng bộ** (`project_metadata_lock` / `_project_lock` là `portalocker.Lock` chặn). Main thread kẹt trong `flock()`, worker thread kẹt chờ main thread. Bằng chứng: `sample` cho thấy main thread ở `fcntl_flock_impl`, cùng process giữ hai file descriptor trên một lock file.
- SIGTERM không có tác dụng vì loop bị chặn; phải SIGKILL worker rồi kích reload.
- Hướng sửa: (a) cấm mọi flock trên event loop, đưa toàn bộ `locked_*` / `project_metadata_lock` vào `asyncio.to_thread`; (b) thêm guard kiểu `EventLoopBridge` ngược: `project_metadata_lock` raise nếu được gọi từ loop thread; (c) test tái hiện bằng hai TTS commit song song.

**Tier video lệch giữa admission và worker**

- Admission (`server/services/narration_delivery_tasks.py::prepare_current_storyboard_narrated_video_duration`) lấy tier qua `strict_reference_durations` → `constrain_durations(resolution=...)`; Veo lite ở 1080p chỉ còn `[8]` (`lib/config/registry.py`: `duration_resolution_constraints={"1080p": [8]}`).
- Worker (`server/services/generation_tasks.py` ~2449) dùng `ctx.video.supported_durations` thô `[4, 6, 8]`, nên với giọng đọc 4,55 giây admission đòi 8 còn worker đòi 6; xác nhận tier nào cũng bị bên kia chặn.
- Hướng sửa: worker phải lấy đúng danh sách đã thu hẹp theo độ phân giải như admission (một nguồn sự thật), và `assert_duration_supported` kiểm tra trên danh sách đó. Test: giọng đọc 4,55 giây, Veo lite 1080p, admission và worker phải cùng ra 8.

**Ngôn ngữ prompt mặc định tiếng Trung**

- `project.source_language` chỉ được ghi ở bước overview (`lib/project_manager.py` ~3821). Project bỏ qua overview thì `target_language` rơi về `"中文"` (`lib/artifact_provenance.py::_DEFAULT_SOURCE_LANGUAGE`), nên image/video prompt ra tiếng Trung dù nguồn tiếng Việt.
- Mã ngôn ngữ và tên ngôn ngữ đang lẫn: `speech_rate` dùng `zh/en/vi`, prompt dùng tên như `中文`. UI tạo project và Project Settings không cho chọn.
- Hướng sửa: chọn ngôn ngữ ở bước tạo project (mã ISO), một hàm map mã → tên hiển thị cho prompt, overview chỉ đề xuất khi người dùng chưa chọn.

### 2.3 Ma sát vận hành

- `uvicorn --reload` kẹt ở "Waiting for connections to close" khi trình duyệt giữ stream video; cần `--timeout-graceful-shutdown`.
- Preset OpenAI không có TTS; OpenAI TTS phải đi qua Custom provider với endpoint `openai-tts`. Docs có ghi nhưng UI không gợi ý.
- Giọng mặc định `Cherry` (DashScope) bị gửi sang OpenAI TTS khi đổi provider; cần reset giọng theo provider.
- Gemini trả rỗng / lỗi nội bộ khoảng 4/22 lần gọi Veo; batch nên tự retry một lần cho các mã lỗi tạm thời trước khi báo thất bại.
- Export của ArcReel là draft Jianying hoặc ZIP, không có mp4 ghép sẵn; bản xem nhanh phải ghép ngoài bằng ffmpeg (trộn TTS lên nền audio Veo hạ 35%).

## 3. Roadmap

### Giai đoạn 0: fork và gộp (1 tuần)

- Fork repo, giữ Python, giữ cấu trúc `lib/ → server/ → frontend/`.
- Merge `fix/gemini-response-schema-additional-properties` và `feat/script-plan-previous-episode-bridge`.
- Bật CI với đúng gate trong `CONTRIBUTING.md`.

### Giai đoạn 1: dọn nền (3 đến 4 tuần)

1. Sửa deadlock khoá file (mục 2.2), thêm test song song. Sau đó bỏ giới hạn TTS tuần tự.
2. Thống nhất nguồn sự thật cho tier video giữa admission và worker.
3. Chọn ngôn ngữ khi tạo project; tách mã và tên ngôn ngữ.
4. Retry tự động cho lỗi provider tạm thời trong batch video.
5. Reset giọng TTS khi đổi provider; gợi ý Custom provider khi preset không có TTS.
6. Preview mp4 một nút bấm (ghép ffmpeg có trộn TTS) bên cạnh export Jianying.

### Giai đoạn 2: chất lượng nội dung (4 đến 6 tuần)

1. Cảnh liền kề biết nhau: prompt cảnh N nhận mô tả cảnh N-1 và N+1 để giữ vị trí nhân vật, hướng nhìn, ánh sáng, thời điểm.
2. Nối khung hình: với cảnh liên tiếp cùng bối cảnh, trích khung cuối video cảnh trước làm first frame cảnh sau (Veo hỗ trợ first/last frame). Render tuần tự theo chuỗi.
3. TTS theo nhân vật và lip-sync: mượn quy tắc đủ điều kiện lip-sync và schema `spatial_layout` / `camera_anchor` của zjt-main (xem tài liệu so sánh).
4. Bộ prompt rules cho tiếng Việt (nhịp câu, độ dài voice-over theo trần 8 giây của Veo).

### Giai đoạn 3: mở rộng (sau khi 1 và 2 ổn)

- Provider Gemini Omni Flash (Interactions API, khác `generateVideos`), Sora, Kling v3 để so chất lượng trên cùng cảnh khó.
- Nếu ghép và transcode thành nút cổ chai: tách dịch vụ media sang Go.

## 4. Ngoài phạm vi

- Node-based canvas.
- Viết lại backend bằng ngôn ngữ khác.
- Thay Claude Agent SDK trong agent runtime.

## 5. Ghi chú công việc đang dang dở (cập nhật 2026-09-10)

Kết quả đến nay: hai tập Bible story đã làm lại trọn chuỗi với "não" mới (style Pixar, overview khán giả, GPT Image 2, Seedance Mini + 2.5, Codex QA). Thành phẩm và báo cáo chi phí nằm trong `projects/bible-story-435fe678/exports/`.

### 5.1 Nhánh code local chưa đẩy (đẩy lên fork, không push upstream)

| Nhánh | Commit | Trạng thái |
|---|---|---|
| `fix/gemini-response-schema-additional-properties` | `f1c68e3e`, `87988791` | Gate xanh; Codex review P2 đã xử lý (chỉ lược ở AI Studio, giữ cho Vertex) |
| `feat/script-plan-previous-episode-bridge` | `cc222eff` | Gate xanh; **còn P1 từ Codex chưa sửa**: screenplay và reference video không được thêm voice-over mới, cần đổi quy tắc mở đầu thành thể hiện bằng hình ảnh |
| `feat/ark-byteplus-model-ids` | `7ee21789` | Gate xanh; ánh xạ `doubao-seedance-*` → `dreamina-seedance-*` khi base URL là bytepluses.com |

### 5.2 Việc sản phẩm đã xác định, chưa làm

1. Deadlock khoá `.project.json.lock` khi hai commit TTS chạy song song (chẩn đoán ở mục 2.2). Tạm né: sinh TTS tuần tự.
2. Tier video lệch giữa admission (áp ràng buộc độ phân giải) và worker (danh sách thô). Tạm né: đặt `duration_seconds` bằng giá trị cả hai bên chấp nhận.
3. Style, `video_backend`, `source_language` ở cấp project chưa có UI hoặc MCP để đặt text tự do; phiên vừa rồi phải ghi thẳng `project.json`. Cần ô style text tự do, chọn ngôn ngữ khi tạo project, chọn model theo project qua MCP.
4. Template asset sheet ép nền trắng (character) và xám (prop), mô tả không ghi đè được; cho phép chọn nền theo project.
5. Cổng review hình bằng vision tích hợp vào workflow (hiện chạy ngoài bằng Codex CLI, harness ở `/tmp/arcreel-qa/`). Quy tắc: review storyboard trước khi render video, mỗi cảnh chỉ render một lần.
6. Hồ sơ khán giả (nhóm tuổi, tông, giới hạn nội dung) thành trường riêng, bơm vào mọi prompt; hiện đang nhét vào overview.
7. Bộ lọc nội dung của nhà cung cấp: OpenAI chặn ảnh nhân vật khoả thân và tượng đất, Seedance từ chối clip vì "audio bản quyền". Cần cơ chế tự viết lại prompt và thử lại một lần trước khi báo lỗi.
8. Reload uvicorn kẹt khi trình duyệt giữ stream; thêm `--timeout-graceful-shutdown` vào lệnh dev trong CONTRIBUTING.

### 5.3 Ý tưởng nâng chất lượng học từ Higgsfield (chưa làm)

- Tách voice-over khỏi ràng buộc "1 câu = 1 cảnh": một câu đọc trải trên 2 shot ngắn 4 đến 5 giây, thay vì 1 shot 8 đến 10 giây.
- Khoá ống kính, ánh sáng, bảng màu theo cảnh; từng shot chỉ đổi hành động và góc máy.
- Nhân vật dùng bộ 6 đến 9 ảnh tham chiếu nhiều góc và biểu cảm (Seedance Mini nhận 9, 2.5 nhận 30) thay vì một sheet.
- Sinh shot khó nhất trước để kiểm tra khả thi rồi mới chạy hàng loạt.
- Lớp audio riêng cho thoại nhân vật, tiếng nền, nhạc; hậu kỳ có cắt theo nhịp và grading.
- Bài test đề xuất: cùng một đoạn 30 giây, bản theo cách hiện tại và bản theo quy tắc trên (shot 4 đến 5 giây, Seedance 2.5, prompt hành động), khoảng 8 đến 10 USD.

### 5.4 Chi phí tham chiếu

Hai tập (2 phút 22 giây) hết 20,81 USD video thực trả trên BytePlus, tổng cả hai vòng thử khoảng 45 USD. Phương án chuẩn khoảng 7 USD một tập, 20 phim × 10 tập dự trù 1.400 đến 1.900 USD, trần 2.400 USD. Chi tiết trong `projects/bible-story-435fe678/exports/bao-cao-chi-phi-san-xuat-2026-09-09.md`.

### 5.5 Học từ waoowaoo (2026-09-10)

Đã trao đổi trực tiếp với agent repo `waoowaoo` (và đợt hai với `zjt-main`, xem `arcreel-vs-zjt-main-drama-shorts-comparison.md` §7-8) và đọc các skill/kiến trúc của họ. Tổng hợp và kế hoạch port ở `docs/research/learn-from-waoowaoo-2026-09-10.md`. Thứ tự đề xuất: prompt rules (character anchor da/tóc/mắt, ref chỉ khóa danh tính, bảng trạng thái entry/exit mỗi shot, 3 câu ràng buộc cố định, kỷ luật diễn xuất) → nối tập bằng exit state → nhịp kịch bản 2/6/8-10 s + gear thiếu nhi → báo giá và đóng băng model trước khi chạy batch → audit `outcome_unknown` khi submit provider. Không port Temporal, lineage graph đầy đủ hay node canvas.

## 6. Kế hoạch nâng cấp đã duyệt (2026-09-10)

Thay thế §3 và gộp §5.2, §5.3, §5.5. Duyệt làm đến đợt 3; đợt 4 để sau. Mỗi đợt kết thúc bằng đo lại trên Bible story bằng Codex QA. Không làm: viết lại bằng Go, node canvas, Temporal, lineage graph đầy đủ.

Bố trí nhánh trên fork: `main` chỉ mirror upstream (workflow sync fast-forward hằng ngày); `dev` là nhánh tích hợp và default branch, mọi PR nhắm vào `dev`; `dev` merge `main` định kỳ để nhận thay đổi upstream. Các workflow chỉ dành cho maintainer upstream (release-please, project-status-sync, docker, nightly) đã tắt trên fork.

### Đợt 0: dọn nợ
1. Merge PR #1 (Gemini schema), #3 (BytePlus model id), #4 (sync upstream) vào fork.
2. PR #2: sửa Codex P1 (screenplay và reference_video chỉ nối tập bằng hình, không thêm lời dẫn), full gate, chuyển ready.
3. Sửa deadlock flock khi TTS commit song song; sửa lệch tier duration giữa admission và worker; thêm `--timeout-graceful-shutdown` vào CONTRIBUTING.

Phát sinh từ đợt 0 (chưa làm, xếp vào đợt 2 mục 11):
- Còn nhiều chỗ gọi `load_project` / `load_script` đồng bộ ngay trong `async def` trên event loop (`lib/config/resolver.py`, `server/media_tools/*`, `server/routers/*`, `project_manager.generate_overview`). Không gây deadlock kiểu PR #7 nhưng chặn loop khi tiến trình khác giữ khóa. Cần audit và đưa ra thread pool.
- Vụ 8 vs 6 trên Seedance ngày 2026-09-09 nhiều khả năng do hai resolver sàn thời lượng TTS (`CurrentTtsSettingsResolver` ở admission vs `ResolvedTtsSettingsResolver.from_audio_lane` ở worker) chứ không phải do thu hẹp theo resolution (PR #8 chỉ sửa phần resolution). Cần hợp nhất hai resolver.

### Đợt 1: chất lượng prompt
4. `feat/prompt-rules-asset`: neo da/tóc/mắt, giày bắt buộc, cấm biểu cảm và tính từ trừu tượng; scene ≥3 điểm neo và chỗ trống blocking; prop chỉ mô tả tĩnh; board tham chiếu 4:3 cận mặt + toàn thân nền trắng.
5. `feat/prompt-rules-storyboard-video`: bảng trạng thái entry/exit mỗi shot; ref chỉ khóa danh tính; 3 câu ràng buộc cố định; kỷ luật diễn xuất; LLM khai `state_changes[]` dạng delta, code bù continuity.
6. `feat/script-rhythm-audience-gear`: nhịp 2/6/8-10 s, test che tên, mở đầu là khoảnh khắc được chọn, gear thiếu nhi 6-10 tuổi (tự viết).
7. Mở rộng PR #2: truyền exit state cảnh cuối tập trước vào script plan.

Đo: style asset 4 → 4.5, storyboard pass 8/17 → ≥14/17.

### Đợt 2: cấu hình và chi phí
8. Đặt `style`, ngôn ngữ, model ảnh/video qua UI và MCP; nhận diện style từ ảnh tham chiếu bằng LLM.
9. Trường audience profile ở project, inject vào mọi prompt.
10. `feat/batch-cost-estimate`: báo giá per second theo resolution trước confirm, ngưỡng mềm/cứng, đóng băng model và tham số vào batch lúc admission.
11. Audit submit provider theo `outcome_unknown`: timeout không tự resubmit; adapter đọc lý do fail có cấu trúc.

### Đợt 3: QA gate và audio nhân vật
12. Codex visual QA thành bước chính thức trong pipeline: chấm content/asset/style/audience, auto regenerate tối đa N lần, ngưỡng tự động và ngưỡng hỏi người.
13. Tự viết lại prompt khi moderation từ chối, retry có giới hạn, log lý do.
14. Cờ `audio_embedded` cấp scene với rule fallback cho bước stitch.
15. Schema `default_voice` + `emotion_voices` cho nhân vật; thử stable voice qua `reference_audio` Seedance trên 2-3 shot, đo drift; ổn mới xét TTS thoại nhân vật và lip-sync.

### Đợt 4 (để sau, chưa duyệt)
16. Sản xuất tập 3-10 Bible story với pipeline mới, mốc chi phí < $10/tập.
17. A/B 30 s kiểu Higgsfield.
