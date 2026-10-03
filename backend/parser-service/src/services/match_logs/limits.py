"""Upload-time checks on a match log's bytes: one message, every enforcement path."""

import csv

from src.core import enums

MATCH_NOT_FINISHED_MESSAGE = "Match is not finished yet: the log has no match_end event"


def match_log_oversize_message(nbytes: int, max_bytes: int, *, filename: str | None = None) -> str | None:
    if nbytes <= max_bytes:
        return None
    who = f"Log file {filename}" if filename else "Log file"
    return f"{who} exceeds the maximum size of {max_bytes} bytes"


def match_log_finished(content: bytes) -> bool:
    """Whether a Workshop log carries its ``match_end`` row.

    The processor fails an unfinished log anyway (``MatchLogProcessor.validate``);
    checking at upload turns a log that is still being written into an
    immediate per-file error instead of a stored object and a doomed parse job.
    The browser auto-uploader relies on that answer to keep waiting.
    """
    lines = content.decode("utf-8", errors="replace").splitlines()
    return any(len(row) > 2 and row[1].strip() == enums.LogEventType.MatchEnd for row in csv.reader(lines))
