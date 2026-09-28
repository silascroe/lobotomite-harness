---
name: verify-before-finish
description: Use after project changes and before completion so success is backed by a fresh verification result.
---

Run a focused validation command after the latest mutation. Read its exit code and relevant output, inspect the resulting files or diff when useful, and repair failures before finishing. Do not report success from intention, an old result, or an unrun check. Finish only with a brief summary grounded in the evidence.

