---
name: test-driven-changes
description: Make behavior changes with a failing check first, then implement and verify the smallest fix.
---

For a behavior change, write or extend a focused test that demonstrates the missing behavior before editing production code. Run that check and confirm it fails for the intended reason. Implement the smallest change that makes it pass, then run the focused check again and the relevant broader suite. If the project has no practical test runner, record the limitation and use the narrowest available executable verification.

