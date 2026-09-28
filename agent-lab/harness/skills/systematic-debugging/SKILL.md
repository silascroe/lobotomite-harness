---
name: systematic-debugging
description: Debug from observable evidence by reproducing, isolating, fixing, and rechecking the failure.
---

Start with the exact error and the smallest reproducible case. Inspect the relevant files and state before guessing. Identify the first incorrect boundary, make one focused repair, and rerun the reproducer. Do not paper over an unknown failure with retries or broad rewrites; if the evidence is insufficient, report the concrete blocker and the next diagnostic action.

