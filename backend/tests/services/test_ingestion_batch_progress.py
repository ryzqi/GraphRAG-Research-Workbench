import pytest

from app.services.ingestion_batch_service import IngestionBatchService


@pytest.mark.parametrize(
    ("total", "completed", "running", "terminal", "expected"),
    [
        (1, 0, 1, False, 50),
        (4, 0, 2, False, 25),
        (4, 1, 1, False, 37),
        (4, 4, 0, True, 100),
        (4, 4, 0, False, 99),
        (0, 0, 0, True, 0),
    ],
)
def test_calculate_progress_percent(
    total: int,
    completed: int,
    running: int,
    terminal: bool,
    expected: int,
) -> None:
    assert (
        IngestionBatchService._calculate_progress_percent(
            total=total,
            completed=completed,
            running=running,
            terminal=terminal,
        )
        == expected
    )
