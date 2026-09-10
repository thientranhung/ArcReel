"""分镜视频时长档位的单一真相源：准入与执行按同一分辨率口径收窄。"""

from __future__ import annotations

import pytest

from lib.narration_delivery import (
    USE_TTS,
    NarrationDeliveryPreparation,
    NarrationTtsStatus,
    prepare_narrated_video_duration,
)
from lib.speech_composition import SpeechMode
from lib.video_duration_tiers import storyboard_video_duration_tiers

# Veo 3.1 在 registry 里声明 1080p/4k 仅 8 秒：分辨率收窄后的档位表与全集不同。
VEO = ("gemini-aistudio", "veo-3.1-generate-preview")
# Seedance 没有分辨率↔时长联动约束：任何分辨率下档位表都等于全集。
SEEDANCE = ("ark", "doubao-seedance-2-0-mini-260615")


def _narration(*, actual_duration_seconds: float | None) -> NarrationDeliveryPreparation:
    return NarrationDeliveryPreparation(
        delivery=USE_TTS,
        unit_id="E1S01",
        speech_mode=SpeechMode.NARRATOR_VOICEOVER,
        tts_status=NarrationTtsStatus.CURRENT,
        artifact_path="audio/E1S01.mp3",
        basis_digest="a" * 64,
        actual_duration_seconds=actual_duration_seconds,
        problems=(),
    )


class TestResolutionNarrowing:
    def test_unset_resolution_keeps_the_model_wide_set(self):
        assert storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution=None) == (4, 6, 8)

    def test_constrained_resolution_narrows_to_its_declared_tiers(self):
        assert storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution="1080p") == (8,)
        assert storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution="4k") == (8,)

    def test_unconstrained_resolution_of_a_constrained_model_keeps_the_set(self):
        assert storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution="720p") == (4, 6, 8)

    def test_no_overlap_is_empty_rather_than_the_unnarrowed_set(self):
        assert storyboard_video_duration_tiers(*VEO, [4, 6], resolution="1080p") == ()

    @pytest.mark.parametrize("resolution", [None, "480p", "720p"])
    def test_model_without_constraints_returns_the_full_set(self, resolution: str | None):
        assert storyboard_video_duration_tiers(*SEEDANCE, range(4, 16), resolution=resolution) == tuple(range(4, 16))

    def test_unregistered_model_passes_the_set_through(self):
        assert storyboard_video_duration_tiers("custom-x", "m", [5, 10], resolution="1080p") == (5, 10)

    def test_normalizes_duplicates_booleans_and_non_positive_values(self):
        assert storyboard_video_duration_tiers(*SEEDANCE, [8, 4, 8, True, 0, -3], resolution=None) == (4, 8)

    def test_empty_input_is_empty(self):
        assert storyboard_video_duration_tiers(*VEO, [], resolution="1080p") == ()


class TestAdmissionAndWorkerAgree:
    """两边把同一份 (型号, 全集, 实际下发分辨率) 交给同一入口，取档结果必然一致。"""

    def test_unset_resolution_requests_the_script_tier_on_a_constrained_model(self):
        tiers = storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution=None)
        result = prepare_narrated_video_duration(
            narration=_narration(actual_duration_seconds=5.5),
            planned_duration_seconds=6,
            supported_durations=tiers,
            confirmed_request_duration_seconds=None,
        )
        assert result.request_duration_seconds == 6
        assert result.adjustment == "exact"
        assert result.allowed

    def test_constrained_resolution_requests_the_only_legal_tier_with_confirmation(self):
        tiers = storyboard_video_duration_tiers(*VEO, [4, 6, 8], resolution="1080p")
        result = prepare_narrated_video_duration(
            narration=_narration(actual_duration_seconds=5.5),
            planned_duration_seconds=6,
            supported_durations=tiers,
            confirmed_request_duration_seconds=None,
        )
        assert result.request_duration_seconds == 8
        assert result.adjustment == "up"
        assert [problem.code for problem in result.problems] == ["reference_duration_confirmation_required"]

    def test_model_without_constraints_rounds_up_by_narration_floor_only(self):
        tiers = storyboard_video_duration_tiers(*SEEDANCE, range(4, 16), resolution="720p")
        result = prepare_narrated_video_duration(
            narration=_narration(actual_duration_seconds=7.2),
            planned_duration_seconds=6,
            supported_durations=tiers,
            confirmed_request_duration_seconds=8,
        )
        assert result.request_duration_seconds == 8
        assert result.adjustment == "up"
        assert result.allowed
