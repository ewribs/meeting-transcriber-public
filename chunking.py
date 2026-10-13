from typing import List


def chunk_transcript(
    transcript: str,
    max_words: int = 1500,
) -> List[str]:
    """
    Split a transcript into chunks while preserving speaker sections.

    Speaker sections are assumed to be separated by blank lines.
    """

    sections = transcript.strip().split("\n\n")

    chunks = []
    current_sections = []
    current_words = 0

    for section in sections:

        words = len(section.split())

        if (
            current_sections
            and current_words + words > max_words
        ):
            chunks.append("\n\n".join(current_sections))
            current_sections = []
            current_words = 0

        current_sections.append(section)
        current_words += words

    if current_sections:
        chunks.append("\n\n".join(current_sections))

    return chunks
