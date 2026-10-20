import pytest
from fsmart.evaluation import calibrate_pairs, retrieval_metrics


def test_known_and_unknown_queries_and_ranked_ap():
    metrics = retrieval_metrics({'a': ['p1','p2'], 'unknown': []}, {'a': ['p1','wrong','p2','p2'], 'unknown': ['wrong']}, k=3)
    assert metrics['precision_at_k'] == pytest.approx(2/3)
    assert metrics['recall_at_k'] == 1
    assert metrics['map_at_k'] == pytest.approx((1+2/3)/2)
    assert metrics['unknown_return_rate'] == 1


def test_threshold_calibration_never_violates_far_and_rejects_invalid_pairs():
    result = calibrate_pairs([.8,.7,.6,.5], [True,True,False,False], target_far=0)
    assert result['far'] == 0 and result['tar'] == 1
    assert result['threshold'] > .6
    with pytest.raises(ValueError):
        calibrate_pairs([float('nan'),.2], [True,False])
