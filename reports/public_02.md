# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.288 | +16.4% | 0.200 | +8.7% | 0.502 | +5.3% | 28% | 81 (330) |
| nw_kyc | 0.372 | -0.7% | 0.241 | -0.3% | 0.590 | -0.4% | 0% | 32 (31) |
| nw_renewal | 0.428 | +0.3% | 0.261 | -0.4% | 0.551 | +0.6% | 5% | 56 (55) |
| ALL | 0.352 | +5.4% | 0.229 | +3.1% | 0.539 | +1.7% | 13% | 169 (416) |

## Changes applied by the controller

3 applied — beneficial: 3

- ks_cancel v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.192 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.153 → **beneficial**
- ks_cancel v5 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 3,
  "decisions": {
    "approved": 3,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 3,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "ks_cancel": 2
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
      "2": 0.392,
      "3": 0.191,
      "4": 0.1,
      "5": 0.101,
      "6": 0.098,
      "7": 0.098,
      "8": 0.101,
      "9": 0.104
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 435,
    "fixed_by": "controller_approved"
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

Credits used: 8 · validation runs: 1 · LLM fix calls: 1