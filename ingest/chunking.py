"""Pure text helpers for the ingest pipeline.

No GCP imports here, so this module can be unit tested anywhere.
"""

CHUNK_CHARS = 1200
OVERLAP_CHARS = 200


def chunk(body: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split text into overlapping character windows, dropping whitespace-only pieces."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk size")

    chunks, start = [], 0
    while start < len(body):
        end = min(start + size, len(body))
        piece = body[start:end].strip()
        if piece:
            chunks.append(piece)
        if end == len(body):
            break
        start = end - overlap
    return chunks
