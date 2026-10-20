"""Evaluation on explicitly labeled held-out queries, never demo-derived accuracy."""
import numpy as np


def retrieval_metrics(truth: dict[str, list[str]], predictions: dict[str, list[str]], k=20):
    precision, recall, ap, unknown = [], [], [], []
    for query_id, relevant in truth.items():
        relevant = set(relevant)
        ranked = list(dict.fromkeys(predictions.get(query_id, [])))[:k]
        if not relevant:
            unknown.append(bool(ranked))
            continue
        hits = 0
        score = 0.
        for rank, photo_id in enumerate(ranked, 1):
            if photo_id in relevant:
                hits += 1
                score += hits / rank
        precision.append(hits / k)
        recall.append(hits / len(relevant))
        ap.append(score / min(k, len(relevant)))
    return {'k': k, 'known_queries': len(ap), 'unknown_queries': len(unknown), 'precision_at_k': float(np.mean(precision)) if precision else None, 'recall_at_k': float(np.mean(recall)) if recall else None, 'map_at_k': float(np.mean(ap)) if ap else None, 'unknown_return_rate': float(np.mean(unknown)) if unknown else None}


def calibrate_pairs(scores, same_person, target_far=.01):
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(same_person, dtype=bool)
    if scores.shape != labels.shape or not scores.ndim == 1 or not np.isfinite(scores).all() or (np.abs(scores) > 1).any() or not labels.any() or labels.all():
        raise ValueError('Cần điểm cosine hữu hạn [-1,1], có cặp cùng người và khác người.')
    candidates = np.unique(np.r_[-1., scores, np.nextafter(scores, np.inf), 1.])
    choices = []
    for threshold in candidates:
        if threshold > 1:
            continue
        predicted = scores >= threshold
        far = float(predicted[~labels].mean())
        tar = float(predicted[labels].mean())
        if far <= target_far:
            choices.append((tar, -far, float(threshold), far))
    if not choices:
        raise ValueError('Không có ngưỡng khả thi trong [-1,1] với FAR mục tiêu.')
    tar, _, threshold, far = max(choices)
    return {'threshold': threshold, 'far': far, 'tar': tar, 'positive_pairs': int(labels.sum()), 'negative_pairs': int((~labels).sum()), 'target_far': target_far, 'small_sample_warning': int((~labels).sum()) < 1000}
