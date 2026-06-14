import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.feedback import (
    AttachmentFeedbackResult,
    AttachmentFeedbackState,
    build_message_feedback,
)


def test_build_message_feedback_replies_for_live_multi_log_results() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.PROCESSED_OK,
            ),
            AttachmentFeedbackResult(
                filename="match-2.log",
                state=AttachmentFeedbackState.PROCESSED_FAILED,
                error_message="missing MatchEnd",
            ),
        ],
        wait_for_result=True,
    )

    assert summary.reactions == ("✅", "⚠️")
    assert summary.reply_text is not None
    assert "match-1.log" in summary.reply_text
    assert "match-2.log" in summary.reply_text
    assert "missing MatchEnd" in summary.reply_text


def test_build_message_feedback_skips_reply_for_already_processed_logs() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.ALREADY_PROCESSED,
            ),
            AttachmentFeedbackResult(
                filename="match-2.log",
                state=AttachmentFeedbackState.ALREADY_PROCESSED,
            ),
        ],
        wait_for_result=True,
    )

    assert summary.reactions == ("✅",)
    assert summary.reply_text is None


def test_build_message_feedback_is_noop_for_already_processed_history_rescan() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.ALREADY_PROCESSED,
            ),
            AttachmentFeedbackResult(
                filename="match-2.log",
                state=AttachmentFeedbackState.ALREADY_PROCESSED,
            ),
        ],
        wait_for_result=False,
    )

    assert summary.reactions is None
    assert summary.reply_text is None


def test_build_message_feedback_reacts_on_history_rescan_when_mixed() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.ALREADY_PROCESSED,
            ),
            AttachmentFeedbackResult(
                filename="match-2.log",
                state=AttachmentFeedbackState.UPLOAD_FAILED,
                error_message="boom",
            ),
        ],
        wait_for_result=False,
    )

    assert summary.reactions == ("✅", "⚠️")


def test_build_message_feedback_reacts_on_history_rescan_for_new_queued_log() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.UPLOADED_QUEUED,
            ),
        ],
        wait_for_result=False,
    )

    assert summary.reactions == ("✅",)


def test_build_message_feedback_skips_reply_for_single_live_result() -> None:
    summary = build_message_feedback(
        [
            AttachmentFeedbackResult(
                filename="match-1.log",
                state=AttachmentFeedbackState.PROCESSED_OK,
            ),
        ],
        wait_for_result=True,
    )

    assert summary.reactions == ("✅",)
    assert summary.reply_text is None
