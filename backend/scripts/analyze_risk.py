"""Freeze the 7470-day cohort and run chronological margin-cost analysis locally."""
import argparse,json
from app.risk_experiment import run,report_path
p=argparse.ArgumentParser();p.add_argument('--ratios',nargs='+',type=float,default=[1,5,10,20,50]);a=p.parse_args()
r=run(a.ratios)
print(json.dumps({'cohort_n':r['cohort_n'],'splits':{k:v['baseline']['n'] for k,v in r['splits'].items()},'boundary_excluded_days':r['boundary_excluded_days'],'scenarios':[{'ratio':s['ratio'],'offset':s['selected_offset_pct'],'test_recall':s['test']['recall'],'additional_catches':s['additional_disruptions_caught'],'additional_false_alarms':s['additional_false_alarms'],'test_loss':s['test_loss'],'baseline_loss':s['baseline_test_loss']} for s in r['scenarios']]},indent=2));print('Report:',report_path())
