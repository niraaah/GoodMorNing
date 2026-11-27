"""Synthetic regression: confidence must not become object transparency."""
import numpy as np
import pytest
from server.segmentation import alpha_from_logits


@pytest.mark.parametrize('score', [.01, .2, 2., 10.])
def test_foreground_is_opaque_and_background_is_clear(score):
    logits = np.full((32, 32), -score, dtype=np.float32)
    logits[8:24, 8:24] = score
    alpha = alpha_from_logits(logits, (64, 64))
    assert alpha.shape == (64, 64)
    assert np.all(alpha[20:44, 20:44] == 1)
    assert np.all(alpha[:10] == 0)
    assert np.all(alpha[:, :10] == 0)
    assert 0 <= alpha.min() <= alpha.max() <= 1


def test_grid_confidence_does_not_print_a_grid_on_the_sticker():
    logits = np.full((32, 32), -1., dtype=np.float32)
    logits[4:28, 4:28] = .2
    logits[4:28:2, 4:28:2] = 4.
    alpha = alpha_from_logits(logits, (96, 96))
    assert np.all(alpha[20:76, 20:76] == 1)


def test_non_square_image_and_boundary_coverage():
    y, x = np.mgrid[:32, :32]
    alpha = alpha_from_logits((x + y - 30.3).astype('float32'), (101, 57))
    assert alpha.shape == (57, 101)
    assert ((alpha > 0) & (alpha < 1)).any()
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 1


@pytest.mark.parametrize('bad', [np.array([[np.nan]]), np.zeros((2,2,2))])
def test_reject_invalid_logits(bad):
    with pytest.raises(ValueError): alpha_from_logits(bad, (20,20))
