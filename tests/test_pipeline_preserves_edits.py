from unittest.mock import patch

from backend.app.db import repo
from backend.app.db.connection import init_db
from backend.app.ingest import pipeline
from backend.app.ingest.storage import Prepared
from backend.app.ml import registry


def _audio_item(library, *, transcript, edited):
    init_db()
    registry.use_stubs()
    item_id = repo.create_item(
        Prepared(
            kind="audio",
            label="запис",
            stored_path="ab/abc.mp3",
            source_path=None,
            content_hash="abc",
            mime="audio/mpeg",
            size_bytes=1,
            created_at="2026-01-01T00:00:00+00:00",
            duration_s=10.0,
        )
    )
    repo.update_item(item_id, transcript=transcript, transcript_edited=int(edited))
    return item_id


def test_reindex_keeps_manual_corrections(library):
    item_id = _audio_item(library, transcript="виправлений людиною текст", edited=True)

    with patch.object(pipeline.asr, "transcribe") as transcribe:
        pipeline.process_audio(item_id)

    transcribe.assert_not_called()
    assert repo.get_item(item_id)["transcript"] == "виправлений людиною текст"


def test_reindex_redoes_machine_transcript(library):
    item_id = _audio_item(library, transcript="машинний текст", edited=False)

    with patch.object(pipeline.asr, "transcribe") as transcribe:
        transcribe.return_value = type(
            "T", (), {"text": "новий машинний текст", "language": "uk", "segments": []}
        )()
        pipeline.process_audio(item_id)

    transcribe.assert_called_once()
    assert repo.get_item(item_id)["transcript"] == "новий машинний текст"
