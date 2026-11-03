"""Calculate study metrics from lecturer-labelled CSV, never invent ground truth.
Columns: predicted (0/1), actual (0/1), accepted (optional 0/1), quality (optional 1..5).
Each row must be a pre-defined unit from a reviewed university course corpus.
"""
import argparse
import csv
import json

def evaluate(rows):
    if not rows:raise ValueError('Evaluation dataset is empty')
    for r in rows:
        if r['predicted'] not in ('0','1') or r['actual'] not in ('0','1'):raise ValueError('Labels must be 0 or 1')
    tp=sum(r['predicted']=='1' and r['actual']=='1' for r in rows)
    fp=sum(r['predicted']=='1' and r['actual']=='0' for r in rows)
    fn=sum(r['predicted']=='0' and r['actual']=='1' for r in rows)
    accepted=[int(r['accepted']) for r in rows if r.get('accepted') in ('0','1')]
    quality=[float(r['quality']) for r in rows if r.get('quality')]
    if any(not 1<=q<=5 for q in quality):raise ValueError('Quality must be 1..5')
    return {'units':len(rows),'true_positives':tp,'false_positives':fp,'false_negatives':fn,
        'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
        'acceptance_rate':sum(accepted)/len(accepted) if accepted else None,
        'mean_instructor_quality':sum(quality)/len(quality) if quality else None}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv_file');args=p.parse_args()
    with open(args.csv_file,newline='',encoding='utf-8') as f:print(json.dumps(evaluate(list(csv.DictReader(f))),indent=2))
