# ArcReel vs zjt-main (智剧通): so sánh kiến trúc cho sản xuất drama shorts

> Trạng thái: khảo sát hoàn tất ngày 2026-09-08. Nguồn: đọc trực tiếp mã ArcReel (nhánh `main`, commit `18409749`) và trao đổi hai chiều với agent đang thụ lý repo `zjt-main` (`/Users/tranthien/Documents/5.GITHUB/zjt-main`). Các đường dẫn phía zjt-main do agent bên đó cung cấp, chưa tự kiểm chứng.
> Mục đích: kho ý tưởng để lục lại khi cần cải thiện chất lượng drama shorts trên ArcReel. Phần 5 là danh sách việc có thể port.

## 1. Tóm tắt kết luận

- ArcReel đủ pipeline cho drama shorts: kịch bản → tài sản → storyboard → video → xuất. Điểm mạnh là kỷ luật vận hành (queue bền, admission trước khi tốn tiền, version mọi đường sửa, stale detection) và custom provider bằng JSON.
- ArcReel **thiếu phần audio nhân vật**: TTS chỉ dùng cho narrator; thoại nhân vật do video model sinh native. Không có lip-sync, voice clone, mixing.
- zjt-main có đủ audio nhân vật (TTS per nhân vật, voice clone, lip-sync qua MiniMax H3) và mô hình không gian / góc máy chi tiết hơn, nhưng vận hành yếu hơn và nhiều tính năng khóa enterprise.
- Việc đáng port sang ArcReel theo thứ tự: (1) mở TTS cho thoại nhân vật + luật lip-sync, (2) thêm `camera_angle` và `spatial_layout` vào schema shot, (3) bước lip-sync sau video như task type mới.

## 2. Hai project là gì

| | ArcReel | zjt-main |
|---|---|---|
| Stack | FastAPI async + SQLAlchemy 2.0 (SQLite/Postgres) + React 19 + Claude Agent SDK | FastAPI + JS thuần + MySQL (pymysql sync, `run_in_executor`), `server.py` ~10k dòng |
| Giấy phép / phiên bản | AGPL-3.0, một bản | Community (giới hạn 10 user, cấm multi-workspace, cấm bypass gate Edition) + enterprise nạp động |
| Loại nội dung | `narration` / `drama` / `ad` × `storyboard` / `reference_video` | StoryType `dialogue` / `narration` / `music_mv` (`config/constant.py:549`) |
| Bề mặt biên tập | TimelineCanvas tuyến tính theo tập; multi-grid; reference-video canvas | `web/storyboard.html` tuyến tính (đường chính cho drama) và `web/video_workflow.html` canvas nút kiểu ComfyUI |
| Xuất | Ghép FFmpeg, draft Jianying (剪映 bản TQ), bundle có thể chỉnh | Zip manifest, draft Jianying đa track, video burn phụ đề |

## 3. So sánh theo 7 trục

### 3.1 Consistency nhân vật

| | ArcReel | zjt-main |
|---|---|---|
| Cơ chế nền | Chỉ reference image qua kênh i2i của provider. Không seed lock, LoRA, IP-Adapter, face-swap | Giống hệt: chỉ reference image |
| Asset sheet | Bắt buộc trước khi sinh (ADR 0073). Nhân vật = ba góc nhìn trên nền trắng, cảnh / đạo cụ = một ảnh, đều 16:9 (ADR 0066) | Ảnh tham chiếu theo thực thể trong world |
| Gọi tham chiếu trong prompt | `@[tên]` đổi thành "图N" theo vị trí mảng; dòng `Reference_Images` khai báo vai trò từng ảnh (`lib/prompt_builders.py::render_storyboard_image_prompt`) | `【【tên】】` / `〖〖đạo cụ〗〗` tra thư viện, gửi URL kèm legend "图1是角色A" (`services/storyboard_reference_prompt_service.py`) |
| Biến thể trang phục | Derivative là sub-identity `@[Tên/biến-thể]`, sinh bằng image-edit từ ảnh gốc, chung giọng và speaker (ADR 0072) | LLM chỉ đánh dấu điểm đổi, code lan truyền trạng thái qua shot, sinh i2i từ ảnh gốc (`services/script_split_character_variant_service.py`) |
| Lưới | Multi-grid N×M chuỗi first / transition / last, cắt ô (`lib/grid/`) | Lưới 2×2 t2i và 3×3 i2i (9 góc con từ ảnh cảnh cha) (`script_writer_core/image_grid_splitter.py`) |
| Nối shot trước | Ảnh storyboard shot trước nối cuối mảng tham chiếu, chỉ tham khảo bố cục và tông; `segment_break=true` để ngắt | Chế độ balanced: ảnh shot trước nối đuôi queue trong cùng nhóm |
| Không gian | Không có | Sổ không gian `spatial_world` + `spatial_layout` + `camera_anchor` (chi tiết ở mục 4.1) |
| Phong cách | 36 style template cấp project, snapshot mở rộng (ADR 0023) | 画风 trong world |
| Hậu xử lý | Không | Che mặt tự động khi sinh video, làm sạch viền lưới (enterprise, Provider pattern) |
| Phát hiện lệch | Artifact manifest theo digest đầu vào, stale hiện trong workflow panel (ADR 0062) | Không có cho asset, chỉ ở gói export |

### 3.2 Góc quay

| | ArcReel | zjt-main |
|---|---|---|
| Cỡ cảnh | Enum `shot_type` 9 giá trị (`lib/script_models.py`) | Text tự do trong `prompt_json.perspective`, shot JSON có shot type |
| Góc máy cao / thấp | **Không có** | Enum `camera_angle`: 平视 / 俯拍 / 仰拍 / 微俯拍 / 荷兰角 (eye-level / high / low / slight-high / Dutch) |
| Chuyển động máy | Enum `camera_motion` 16 giá trị khớp từ vựng MiniMax Hailuo và Alibaba Wan, chèn nguyên văn vào video prompt | camera_movement text; node điều khiển camera 7 preset (`web/js/camera_control_node.js`) |
| Ống kính / tiêu cự | Không | Không |
| Chuẩn hóa drift | Gập `_` / `-` / hoa thường về enum; ngoài từ vựng hạ về Medium Shot / Static kèm warning | Không có (text tự do nên dễ trôi) |
| Áp đặt bố cục | Chỉ qua prompt và ảnh tham chiếu | Director Stage: sân khấu 3D trong trình duyệt, mannequin 5 thể hình, 12 pose, 16 khớp, 11 preset máy, FOV, render snapshot làm ảnh bố cục tham chiếu; kết hợp panorama 360 (`docs/video/director_stage_node.md`, `web/js/director_stage_editor.js`) |

### 3.3 Edit storyboard

| | ArcReel | zjt-main |
|---|---|---|
| Mô hình dữ liệu | Shot trong `scripts/episode_N.json`, mỗi lần sinh là version mới trong `versions/`, current trỏ một bản | `storyboard_scene_asset` nhiều ứng viên, scene trỏ `selected_first_frame_id` / `selected_last_frame_id` / `selected_video_id` (`docs/storyboard/storyboard_design.md`) |
| Đường sửa | Sửa prompt rồi sinh lại; image-edit bằng lệnh với ảnh hiện tại là tham chiếu duy nhất, không đổi prompt (ADR 0050); upload thay thế | Sửa prompt; chat với trợ lý theo scene để image-edit hội thoại; upload ứng viên; batch đổi model / sinh lại nhiều scene |
| Chèn shot giữa chừng | Sửa kịch bản thủ công hoặc qua agent | Agent suy luận từ ngữ cảnh trước sau (`storyboard-insert` skill) |
| End frame | Có (EndFramePicker) | Có |
| Version cấp tập | Không (chỉ per asset) | Không (chỉ per asset) |
| UI | `frontend/src/components/canvas/timeline/`: ImagePromptEditor, VideoPromptEditor, PromptPreviewPanel, ReferencesSection, ImageEditButton, VersionTimeMachine, GridPreviewPanel | `web/storyboard.html` |

### 3.4 Audio

| | ArcReel | zjt-main |
|---|---|---|
| TTS narrator | DashScope Qwen3 TTS Flash; OpenAI-compatible qua custom endpoint | IndexTTS tự host (`utils/index_tts_util.py`) |
| TTS thoại nhân vật | **Không**: `lib/narration_delivery.py::canonical_narration_text` chỉ lấy utterance owner NARRATOR | Có, per nhân vật, đổi giọng per dialogue group |
| Voice clone | Không | Reference audio per nhân vật (`docs/audio/reference_audio_guide.md`) |
| Emotion | Không | Emotion vector (enterprise, `services/dialogue_emotion.py`) |
| Thoại do video model sinh | Đường chính. `voice_consistency`: `native` (reference audio, chỉ reference-video mode + model hỗ trợ) / `soft` (mô tả giọng trong prompt) / `none` | Tùy chọn `audio_embedded` per scene |
| Lip-sync | Không | Scene loại `digital_human` khóa MiniMax H3 (task type 35), TTS trước rồi ghép khẩu hình (`docs/storyboard/storyboard_digital_human.md`) |
| Mixing nhạc nền, transition | Không, làm trong Jianying | Không, làm trong Jianying |

### 3.5 Provider

| | ArcReel | zjt-main |
|---|---|---|
| Abstraction | 4 Protocol Text / Image / Video / Audio, registry name→factory, construction qua `lib/backend_assembly/` | Hơn 30 driver kế thừa `BaseVideoDriver`, registry tên→class (`task/visual_drivers/driver_factory.py`); LLM tách ở `llm/` |
| Bảng cấu hình | `lib/config/registry.py` `PROVIDER_REGISTRY`, pricing khai báo (`lib/pricing/`) | `config/unified_config.py`: task type id → driver → giá → tham số → cờ UI |
| Built-in | Gemini (AI Studio, Vertex), Volcengine Ark, Grok, OpenAI, Vidu, DashScope, MiniMax, Kling, Agnes | Đa số qua aggregator TQ (RunningHub, 多米, 火山); driver common gọi thẳng Kling / Veo / GPT-image / Grok |
| Custom không cần code | Có, bản mở: JSON endpoint definition + preview request / check response / trial run (`lib/custom_provider/`) | Chỉ enterprise ("user module" qua RPC + ABI JSON). Community phải viết driver Python |
| Model video cho drama | User chọn; có audio native: Veo 3.1, Seedance 2.x, Wan 2.7, Kling | Không mặc định cứng; Kling, Vidu Q2/Q3, Seedance, Veo3, Sora2, Wan 2.2/3, MiniMax H3, LTX 2/2.3, Happy Horse |

### 3.6 Vận hành

| | ArcReel | zjt-main |
|---|---|---|
| Queue | Persist trong DB, một worker per process, capacity per-provider × media lane, cancel giây (ADR 0006), resume chỉ khi có provider job id (ADR 0007) | ai_tools / async_tasks / download_queue, retry tối đa 30, hết hạn 7 ngày; APScheduler tách tiến trình |
| Trước khi tốn tiền | Batch admission all-or-nothing: ADMITTED / CONFIRMATION_REQUIRED / BLOCKED (`lib/batch_admission.py`, ADR 0061) | Không; trừ tiền per call |
| Chi phí | Ledger per api_call, usage là projection (ADR 0076) | Compute account per user, admin đổi giá và model nóng, nạp WeChat Pay, hoa hồng (enterprise) |
| Đa user | Một admin, có chỗ mở rộng | Có |
| Lint đặc thù | ruff, basedpyright, import-linter layering, deptry, audit_tests | `scripts/lint_blocking_calls.py` R1-R8 chặn blocking call trong async |

### 3.7 Agent

| | ArcReel | zjt-main |
|---|---|---|
| Runtime | Claude Agent SDK, `SessionActor` per session (ADR 0028), transcript trong SQL (ADR 0029) | PM agent + expert agents (`script_writer_core/agents/`) |
| Profile | `agent_runtime_profile/` materialize theo `content_mode` vào `<project>/.claude/` (`lib/profile_manifest.py`) | Không materialize; skill markdown ở `script_writer_core/skills/` |
| Tools | `server/tool_runtime.py` + `server/media_tools/`, in-process MCP và remote MCP `/mcp` cho agent ngoài | `mcp_tool.py` in-process, ask_user mixin |
| Agent ngoài | Remote MCP + API key `arc-` | Command API + CLI cùng schema (`storyboard-agent-api/v1`), skill sẵn cho Claude Code và Codex |
| Kiểm duyệt | Không | content-compliance-checker theo chuẩn TQ, kiểm tra hook cuối tập |
| QC loop | Cổng duyệt script_plan → prompt_authoring, quarantine output lỗi | Tối đa 5 vòng khi tách kịch bản, retry chỉ đoạn lỗi |

## 4. Chi tiết đáng copy từ zjt-main

### 4.1 Sổ không gian và neo máy quay

Nguồn (repo mở): schema ví dụ trong system prompt `llm/script_parser.py:913-1105`; quy tắc `script_writer_core/skills/script-parser/SKILL.md` mục 21 (dòng 81-103); sửa liên tục `repair_spatial_layout_continuity` tại `llm/script_parser.py:522`. Engine tiêu thụ (`services/storyboard_spatial/`) là enterprise. Tọa độ chuẩn hóa -1..1, `schema_version: 2`.

Cấp tập (cạnh characters / locations / props / shot_groups):

```json
"spatial_world": {
  "space_units": [{
    "space_unit_id": "space_prop_001_cabin",
    "name": "泡泡蒸汽车驾驶室",
    "owner_type": "prop | location",
    "owner_id": "prop_001",
    "location_ids": ["loc_001", "loc_002"],
    "coordinate_frame": {
      "frame_id": "frame_prop_001_cabin",
      "origin": "驾驶室中心",
      "axes": {"x_positive": "车辆自身右侧", "y_positive": "车辆自身前方", "z_positive": "上方"},
      "scale": "normalized_unit_box | normalized_scene_box",
      "locked": true
    },
    "anchors": [
      {"anchor_id": "front_driver_seat", "label": "驾驶座", "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25}},
      {"anchor_id": "front_passenger_seat", "label": "副驾驶座", "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25}}
    ]
  }]
}
```

Luật: một tập nhiều space unit, không dùng một hệ tọa độ lớn. Trục và anchor đã lập thì shot sau chỉ tham chiếu. Không gian mới phải vào registry trước rồi shot mới được tham chiếu.

Cấp shot (cạnh shot_type / camera_angle / camera_movement / presentation):

```json
"characters_present": ["char_001"],
"focus_character_ids": ["char_001"],
"spatial_layout": {
  "schema_version": 2,
  "space_unit_refs": ["space_prop_001_cabin"],
  "camera_pose": {
    "space_unit_id": "space_prop_001_cabin",
    "eye": {"x": 0.0, "y": -0.8, "z": 0.6},
    "target": {"x": 0.3, "y": 0.45, "z": 0.35},
    "up": {"x": 0, "y": 0, "z": 1},
    "fov": "medium"
  },
  "camera_anchor": {
    "description": "从车外左侧车窗外向车内拍摄，机位位于【【奶酪_Cheese】】的左前方约30度，隔着车窗玻璃观察车内",
    "camera_position": "车外左侧车窗外",
    "shooting_direction": "穿过左侧车窗向车内驾驶台方向拍摄",
    "relative_to_character": {"character_id": "char_001", "name": "奶酪_Cheese", "position": "左前方30度", "distance": "隔着车窗的中景距离"},
    "view_direction": "rear_to_front | front_to_rear | left_to_right | right_to_left | unknown",
    "screen_axis_mapping": {"container_left": "screen_left", "container_right": "screen_right", "container_front": "screen_depth_front", "container_rear": "screen_depth_back"},
    "screen_composition": "【【奶酪_Cheese】】位于画面左侧并贴近左侧车窗玻璃，【【奶昔_Milkshake】】位于画面右侧驾驶座"
  },
  "location_path": [{"location_id": "loc_001", "name": "...", "role": "current_scene"}],
  "containers": [{
    "container_type": "prop", "prop_id": "prop_001", "name": "...",
    "area": "驾驶室", "position_in_location": "...",
    "slots": [{
      "space_unit_id": "space_prop_001_cabin",
      "anchor_id": "front_passenger_seat",
      "slot_id": "front_left_seat",
      "slot": "驾驶室左侧座位",
      "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25},
      "physical_position": {"row": "front", "side": "vehicle_left | vehicle_right | center", "basis": "container_forward_direction"},
      "position_basis": "physical_slot",
      "screen_position": "画面左侧",
      "occupant_type": "character | prop",
      "character_id": "char_001", "name": "...",
      "pose": "当前镜头姿态或动作",
      "visibility": "visible | partial | offscreen | occluded",
      "framing_role": "primary_subject | secondary_continuity | background | offscreen_continuity"
    }]
  }],
  "loose_positions": [],
  "continuity": {
    "unchanged_slots": [],
    "changed_positions": [{
      "character_id": "char_002",
      "from_container_id": "prop_001", "from_slot": "副驾驶座",
      "to_container_id": null, "to_slot": null,
      "change_type": "moved_slot | entered_container | left_container | exited_scene | entered_scene",
      "reason": "真实空间变化原因"
    }],
    "notes": "..."
  }
}
```

Ba bất biến phải giữ khi port:

1. Tách vật lý khỏi chiếu hình: `slot_id` / `physical_position` / `anchor_id` không đổi theo góc máy, chỉ `screen_position` và `camera_pose` đổi. Không suy "đổi ghế" từ việc trái / phải trên màn hình đảo.
2. Visibility khác tồn tại: nhân vật offscreen / occluded rời `characters_present` nhưng giữ trong `spatial_layout` với `framing_role: offscreen_continuity`. Chỉ `changed_positions` mới được di chuyển. Shot N phải checklist mọi slot của shot N-1.
3. `camera_anchor.description` phải ghép được vào câu đầu của mô tả frame mở mà không mâu thuẫn (nhìn qua cửa kính nghĩa là máy ở ngoài xe).

### 4.2 Luật gán lip-sync

Nguồn: tầng LLM `presentation ∈ {video, digital_human}` (`script-parser/SKILL.md` mục 19, dòng 69-75); tầng code quyết định cuối `services/storyboard_scene_type.py::resolve_scene_video_type(shot, dialogues)`. Kiểm tra theo thứ tự, dừng ở điều kiện đầu khớp:

1. `speaker_count != 1` → video. Đếm distinct `character_id` trong `dialogue[]` có text; dòng không có character_id là narration và bỏ qua (voice-over không tính là speaker).
2. `len(visible_character_ids) != 1` → video. Lấy từ `characters_present`, dedupe.
3. Speaker đọc từ dialogue nguồn (trước khi map DB id) `!= 1` → video.
4. Speaker id khác visible id → video (`speaker_not_visible`, ví dụ macro con muỗi + voice-over).
5. Từ khóa hành động mạnh trong action / description / camera_movement (打斗 / 追逐 / 跑 / 爆炸 / fight / chase / run / explode) → video, dù LLM bảo digital_human.
6. LLM `presentation` = digital_human / lip_sync / 对口型 → digital_human; = video / image / i2v → video.
7. Heuristic khi LLM không nói: shot_type hoặc camera_angle chứa cận / đặc tả (近景 / 特写 / close-up / MCU / CU / ECU) hoặc shot_type rỗng → digital_human; ngược lại → video.

Meta trả về: speaker_count, speaker_character_id, visible_character_count, presentation_source (rule / llm / heuristic), presentation_reason, lưu vào video_config của scene để debug. Hệ quả: một người nói trong khung nhiều người luôn là video; muốn lip-sync thì bước tách kịch bản phải chia cảnh đối thoại nhiều người thành shot đơn người trước (SKILL.md mục 18).

### 4.3 Các ý nhỏ khác

- `camera_angle` enum 5 giá trị (mục 3.2).
- Director Stage nếu muốn kiểm soát bố cục bằng snapshot 3D thay vì prompt.
- QC loop tách kịch bản: tối đa 5 vòng, retry chỉ đoạn lỗi.
- Lint chặn blocking call trong async (`scripts/lint_blocking_calls.py`), hữu ích nếu ArcReel có đường sync lẫn vào.
- Agent ngoài: bộ command API + CLI cùng schema và skill sẵn cho Claude Code / Codex.

## 5. Việc có thể port sang ArcReel

| Ưu tiên | Việc | Điểm chạm trong ArcReel | Ghi chú |
|---|---|---|---|
| 1 | Mở TTS cho thoại nhân vật | `lib/narration_delivery.py::canonical_narration_text` (lọc owner), `lib/speech_composition/` (`SpeechOwner`), `server/services/narration_delivery_tasks.py` | Utterance đã có `speaker`, chỉ cần cho phép owner CHARACTER đi TTS; cần quyết định trộn với âm gốc video thế nào |
| 1 | Audio backend có voice clone | `lib/audio_backends/base.py` (thêm trường reference audio vào request), `lib/audio_backends/registry.py`, `lib/backend_assembly/specs.py`, `lib/pricing/lookup.py` | Ứng viên: IndexTTS, MiniMax speech, ElevenLabs, Fish Audio. Nhân vật đã có `refs_audio/` |
| 1 | Luật lip-sync (mục 4.2) | Hàm thuần trong `lib/`, gọi từ `lib/workflow_plan.py` hoặc lúc enqueue video | Cần `characters_present` (đã có `characters_in_*`) và utterances (đã có) |
| 2 | Bước lip-sync sau video | Task type mới trong `lib/generation_type_buckets.py`, executor trong `server/services/`, đi qua generation queue như TTS (ADR 0010) | Provider: MiniMax H3 (đã có endpoint JSON `minimax-h3.json`), Kling lip-sync |
| 2 | `camera_angle` enum | `lib/script_models.py` cạnh `shot_type`, `lib/prompt_utils.py` (render YAML + validate), `frontend/src/types` + ImagePromptEditor, i18n zh/en/vi | Chuẩn hóa drift như hai enum hiện có; mặc định Eye-level |
| 3 | `spatial_layout` + `camera_anchor` tùy chọn (mục 4.1) | `lib/script_models.py` (Optional, `extra="forbid"`), prompt hướng dẫn trong `lib/prompt_builders_script.py`, subagent `normalize-drama-script` | Bắt đầu bằng `camera_anchor` + `containers[].slots[]` + `continuity`; bỏ `camera_pose` tọa độ nếu chưa có engine tiêu thụ |
| 3 | Version cấp tập | `lib/version_manager.py` | Cả hai project đều thiếu |
| 3 | Ảnh shot trước với vai trò rõ trong legend | Đã có ("图4为上一分镜图，只参考构图与色调") | Không cần làm |

## 6. Điểm zjt-main đã nhận sẽ vay mượn từ ArcReel

Đã gửi cho agent bên đó: enum `shot_type` / `camera_motion` với chuẩn hóa drift; `UnitAdmissionTicket` fold thành ADMITTED / CONFIRMATION_REQUIRED / BLOCKED; custom endpoint JSON với preview / check / trial run. Bên đó xác nhận đây là ba thứ community đang thiếu.

## 7. Đợt trao đổi thứ hai (2026-09-10)

Hỏi thêm 6 điểm sau khi học từ waoowaoo (xem `learn-from-waoowaoo-2026-09-10.md`). Bên zjt-main trả lời từ code và docs, chưa có số liệu chất lượng thực tế vì chưa chạy batch nào.

### 7.1 Trộn TTS với audio gốc của video model
Quyết định ở lúc preview/export, không ở lúc sinh video. Cờ per-scene `audio_embedded` (1 = giữ âm gốc, bỏ TTS; 0 = ưu tiên TTS). Rule cứng trong `services/storyboard_export_service.py::resolve_scene_keep_video_audio`:
- video không có audio stream → không giữ;
- `audio_embedded=1` → giữ âm gốc;
- `audio_embedded=0` nhưng chưa có TTS → vẫn giữ âm gốc để không câm cả đoạn;
- có TTS và không chọn âm gốc → mute video, mix TTS bằng ffmpeg (`_build_scene_audio`).
Scene lip-sync mặc định `audio_embedded=1` vì MiniMax H3 đã nhúng thoại. Không có mixing nhạc nền.

**Đáng port**: cờ `audio_embedded` cấp scene + rule fallback này gọn hơn cách ArcReel đang stitch (TTS mix đè lên audio model với volume 0.35). ArcReel có `narration_delivery` (`use_tts` vs `post_production`) ở cấp project; nên hạ xuống cấp scene với rule fallback tương tự.

### 7.2 Voice clone
IndexTTS tự host (`utils/index_tts_util.py`, emotion vector 8 chiều + emotion reference audio). Không có ElevenLabs/Fish/MiniMax TTS. Tiếng Việt: không cam kết, IndexTTS thiên Trung/Anh. Mẫu giọng tối đa 20 s, vượt thì tự cắt. Schema: `character.default_voice` (URL) + `character.emotion_voices` (map cảm xúc → audio) trong `model/character.py`, override được per dialogue group. Có sinh mẫu giọng tự động từ mô tả nhân vật qua RunningHub.

**Cho ArcReel**: schema `default_voice` + `emotion_voices` đáng chép vào asset nhân vật (ArcReel đã có `refs_audio/`). Provider tiếng Việt phải tự thử; ứng viên: OpenAI TTS (đang dùng, không clone), Gemini TTS, MiniMax speech, ElevenLabs.

### 7.3 Lip-sync MiniMax H3 với nhân vật 3D
Không có dữ liệu. Ràng buộc kỹ thuật: chỉ nhận đúng 1 mặt trong khung (`services/storyboard_scene_type.py`); định tuyến dual-model ở `docs/storyboard/storyboard_digital_human_dual_model_routing_design.md`. Phải tự đo trên Pixar-style.

### 7.4 Sổ không gian khi nhân vật di chuyển
LLM + rule, có entry/exit state tương đương waoowaoo:
- Tách theo đoạn: mỗi đoạn nhận `previous_state` (slot cuối đoạn trước) + `previous_camera_summary` làm entry state (`llm/script_parser.py::_build_incremental_spatial_prompt`).
- LLM chỉ khai thay đổi qua `spatial_intent.state_changes[]` với động từ enter/move/exit/pickup/put_down/transfer; không đổi thì mảng rỗng. `characters_present` chỉ là visibility, cấm khai `exit` vì ra khỏi khung.
- Rule bù `repair_spatial_layout_continuity` (`llm/script_parser.py:522`) mang nhân vật shot trước còn trong container sang shot sau dạng offscreen_continuity nếu LLM quên. Engine đầy đủ là enterprise.
- `services/script_split_engine.py` validate mọi space_unit_id/anchor_id/slot_id tồn tại trước QC.

**Cho ArcReel**: kết hợp với bảng trạng thái entry/exit của waoowaoo. Cách làm hợp lý: LLM khai `state_changes[]` (delta), code tự suy state tuyệt đối cho shot sau, validate id tồn tại. Đây là bước cụ thể hóa mục 5 (ưu tiên 3) của tài liệu này.

### 7.5 Thiếu nhi / hoạt hình 3D
Không có preset trẻ em, không có rule độ tuổi trong skill kịch bản. `world.style` là text tự do, nhận diện được từ ảnh tham chiếu bằng LLM (`docs/backend/script_style_recognition.md`); style inject làm suffix cuối mọi prompt sinh ảnh. Kiểm duyệt theo chuẩn Trung Quốc, không có kid-safe. Cả zjt-main lẫn waoowaoo đều không có: **gear thiếu nhi là thứ ArcReel phải tự viết**, và là điểm khác biệt.

Ý nhỏ đáng lấy: nhận diện style từ ảnh tham chiếu bằng LLM để điền `style` thay vì bắt user gõ (ArcReel hiện phải sửa project.json tay).

### 7.6 Chi phí
Đơn vị nội bộ "compute point", per implementation trong `config/unified_config.py` (int hoặc dict theo duration) + `power_modifiers` theo resolution/mode, admin đổi trong DB, hot reload. Không map thẳng sang tiền provider. Có ước tính trước batch (`POST /api/storyboard/{id}/estimate-missing-videos-power`) và `power_confirm.py` hỏi user khi vượt ngưỡng mềm/cứng. Trừ tiền per call sau submit, không all-or-nothing. Sự cố 2026-09-01: vòng lặp confirm timeout gây trừ phí lặp.

**Cho ArcReel**: ngưỡng mềm/cứng để hỏi confirm là ý hay, kết hợp với báo giá per_second (từ waoowaoo) vào admission hiện có.

### 7.7 Ghi nhận vận hành
- BytePlus liệt kê `dreamina-seedance-2-0-*` trong khi driver gọi `doubao-seedance-2-0-*`, họ map qua `volcengine_oversea.model_aliases`. ArcReel đã sửa cùng vấn đề ở PR #3 (`ark_api_model_name`).
- Gemini trả 401 khi thấy header Bearer kể cả có `x-goog-api-key`; họ chọn header theo host.
- User bên zjt phàn nàn UI khó dùng, node canvas bị giấu sau card workflow. Ghi nhận cho quyết định điểm vào của ArcReel, không đổi quyết định "không làm node canvas".

## 8. Kế hoạch port gộp (zjt-main + waoowaoo)

Xem thứ tự tổng ở `learn-from-waoowaoo-2026-09-10.md` §4. Bổ sung từ zjt-main:
- Cờ `audio_embedded` cấp scene + rule fallback (7.1) → vào nhánh stitch/export.
- Schema `default_voice` + `emotion_voices` cho nhân vật (7.2) → chuẩn bị cho thử nghiệm stable voice.
- `state_changes[]` delta + repair rule (7.4) → ghép với entry/exit state trong nhánh storyboard prompt.
- Ngưỡng mềm/cứng confirm chi phí (7.6) → nhánh `feat/batch-cost-estimate`.
- Nhận diện style từ ảnh tham chiếu (7.5) → giải quyết luôn việc thiếu UI cho `style` (roadmap §5.2).
