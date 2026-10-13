from pathlib import Path


def remove_wavs(
    meeting_dir: Path,
) -> tuple[int, int]:
    """
    Remove only audio/*.wav from a meeting folder.

    Returns:
        (files_removed, bytes_removed)
    """

    audio_dir = (
        meeting_dir / "audio"
    )

    if not audio_dir.exists():
        return 0, 0

    wav_files = sorted(
        audio_dir.glob("*.wav")
    )

    files_removed = 0
    bytes_removed = 0

    for wav_file in wav_files:
        size = wav_file.stat().st_size

        wav_file.unlink()

        files_removed += 1
        bytes_removed += size

    try:
        audio_dir.rmdir()
    except OSError:
        pass

    return (
        files_removed,
        bytes_removed,
    )
