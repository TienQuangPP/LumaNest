"""Evaluate labeled retrieval output or calibrate a threshold using validation pairs."""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsmart.evaluation import calibrate_pairs, retrieval_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    retrieval = sub.add_parser('retrieval')
    retrieval.add_argument('--truth', type=Path, required=True)
    retrieval.add_argument('--predictions', type=Path, required=True)
    retrieval.add_argument('--k', type=int, default=20)
    calibrate = sub.add_parser('calibrate')
    calibrate.add_argument('--pairs', type=Path, required=True)
    calibrate.add_argument('--model-key', required=True)
    calibrate.add_argument('--target-far', type=float, default=.01)
    calibrate.add_argument('--output', type=Path, default=Path('config/calibration.json'))
    args = parser.parse_args()
    if args.command == 'retrieval':
        if args.k <= 0:
            parser.error('k must be positive')
        result = retrieval_metrics(json.loads(args.truth.read_text(encoding='utf-8')), json.loads(args.predictions.read_text(encoding='utf-8')), args.k)
    else:
        if not 0 <= args.target_far <= 1:
            parser.error('target-far must be in [0,1]')
        pairs = json.loads(args.pairs.read_text(encoding='utf-8'))
        result = {'model_key': args.model_key, **calibrate_pairs([x['similarity'] for x in pairs], [x['same_person'] for x in pairs], args.target_far)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
