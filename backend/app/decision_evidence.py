"""Evidence gate for office-operation labels; weather is never proof of operation.

A high-confidence evidence category is not a calibrated numerical probability.
Raw evidence remains retained so exclusions are reviewable and reversible.
"""
POLICY_VERSION = 'confirmed-office-evidence-v1'

def eligible(record: dict) -> bool:
    evidence = record.get('decision_evidence') or {}
    return bool(
        record.get('cause') == 'weather'
        and record.get('status') in {'NORMAL', 'CLOSED', 'DELAYED_ARRIVAL', 'EARLY_DISMISSAL'}
        and record.get('verification') == 'official'
        and evidence.get('reviewed') is True
        and evidence.get('date_confirmed') is True
        and evidence.get('scope') == 'nonessential_offices'
        and evidence.get('category') == 'official_with_dated_corroboration'
        and record.get('source_url')
        and record.get('corroborating_source_url')
        and evidence.get('rationale')
    )

def describe(records: list[dict]) -> dict:
    accepted = [r for r in records if eligible(r)]
    return {'policy_version': POLICY_VERSION,
            'label': 'Confirmed office decisions: official notice with dated corroboration. High-confidence evidence category, not a calibrated 95% probability.',
            'confidence_probability': None,
            'institution_days': len(accepted),
            'unique_days': sorted({r['day'] for r in accepted}),
            'excluded_records': [{'day': r['day'], 'institution': r['institution'],
                                  'reason': (r.get('decision_evidence') or {}).get('exclusion_reason', 'Unconfirmed office-operation evidence')}
                                 for r in records if not eligible(r)],
            'limitations': 'Weather API observations corroborate weather only. No notice does not mean open. Proxy office decisions do not confirm USDA facility operations.'}
