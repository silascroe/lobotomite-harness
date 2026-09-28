# Static page smoke test

Build a polished, self-contained single-page site for a fictional app called “Northstar Field Notes.” It is a small personal field notebook for recording observations outdoors.

Create `index.html`, `styles.css`, and `app.js` in the project directory. The page should:

- Have a clear hero section with the product name, a concise description, and a primary “Add observation” action.
- Include a form that accepts an observation title, location, and note text.
- Render submitted observations as cards on the page without reloading.
- Include a visible observation count and an empty-state message before the first observation.
- Look intentional on both a phone-sized viewport and a desktop viewport. Use plain HTML, CSS, and JavaScript only; do not use a framework, CDN, remote font, or external image.
- Use semantic elements and labels, sensible keyboard focus styles, and reasonable color contrast.

Keep the design coherent and restrained: dark sky/navy background, warm paper-like cards, and one strong accent color. The result should feel like a real tiny product, not a raw demo dump.

Move through the workflow explicitly: inspect the project, record a short plan with `workflow_checkpoint`, implement the page, verify it with `node --check app.js`, review the complete change with `git_diff`, and then call `finish` with an honest summary. The validation command does not require network access.

