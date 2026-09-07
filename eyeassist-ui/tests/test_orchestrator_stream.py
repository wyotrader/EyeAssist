from pathlib import Path


def test_orchestrator_stream_does_not_buffer_chunks():
    source = Path(__file__).resolve().parents[2] / "pipeline" / "orchestrator" / "orchestrator.py"
    text = source.read_text()
    stream_section = text.split('async def orchestrate_stream', 1)[1]
    assert "chunks = []" not in stream_section
    assert "run_in_executor" not in stream_section
    assert "for chunk in synthesize_response_stream" in stream_section
