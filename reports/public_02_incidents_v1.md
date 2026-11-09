# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.248 | +0.0% | 0.184 | +0.0% | 0.476 | +0.0% | 0% | 330 (330) |
| nw_kyc | 0.375 | +0.0% | 0.242 | +0.0% | 0.592 | +0.0% | 0% | 31 (31) |
| nw_renewal | 0.427 | +0.0% | 0.262 | +0.0% | 0.548 | +0.0% | 5% | 55 (55) |
| ALL | 0.334 | +0.0% | 0.222 | +0.0% | 0.530 | +0.0% | 3% | 416 (416) |

## Changes applied by the controller

0 applied — 


## Governance

```
{
  "approval_requests": 1,
  "decisions": {
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 0,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "ks_cancel": 1
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.509,
      "3": 0.502,
      "4": 0.49,
      "5": 0.504,
      "6": 0.492,
      "7": 0.502,
      "8": 0.499,
      "9": 0.496
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": null,
    "fixed_by": null
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0