"""Actionable checker descriptions; grades remain the original boolean checks."""

DETAILS = {
    # Shared by the browser tasks.
    "runs_without_errors": ("Load the page without uncaught JavaScript errors or missing local files.", ["app.js", "index.html"]),
    "loads_styles_and_script": ("Load styles.css as a stylesheet and app.js as a script from index.html.", ["index.html"]),
    "local_assets": ("Use only local files: no remote fonts, scripts, styles or images.", ["index.html", "styles.css"]),
    "focus_visible": ("Every control reached with Tab needs a visible focus indicator; never remove the outline without a replacement.", ["styles.css"]),
    "responsive_layout": ("Fit a 375px phone without sideways scrolling (viewport meta tag plus a fluid layout) and fit a desktop window.", ["index.html", "styles.css"]),
    # Static page.
    "product_heading_and_action": ("Show Northstar Field Notes in a visible h1 or h2 and a visible control named Add observation.", ["index.html"]),
    "semantic_structure": ("Use header, main and form elements.", ["index.html"]),
    "labeled_fields": ("Give the title, location and note fields labels (label for=, or aria-label).", ["index.html"]),
    "empty_state": ("Show an empty-state message before the first observation and hide it once one is added.", ["app.js", "index.html"]),
    "submit_adds_card": ("Submitting the form must add a card showing the title, location and note without reloading the page (call preventDefault).", ["app.js"]),
    "keeps_all_cards": ("Each submission must add a new card and keep the earlier ones.", ["app.js"]),
    "count_updates": ("Show an observation count that reads 1 after the first observation and 2 after the second.", ["app.js", "index.html"]),
    "readable_contrast": ("Give text at least 3:1 contrast against its background.", ["styles.css"]),
    # Mini project.
    "signal_garden_heading": ("Include a visible h1 headed Signal Garden.", ["index.html"]),
    "description": ("Include a visible paragraph describing the page.", ["index.html"]),
    "semantic_main": ("Put the primary content inside a main element.", ["index.html"]),
    "action_updates_status": ("Using the primary button must visibly change the text of a status element.", ["app.js"]),
    "keyboard_operable": ("The primary action must work from the keyboard (Tab to it, press Enter); use a real button element.", ["index.html", "app.js"]),
    # File round-trip.
    "has_note": ("Create agent-check.md.", ["agent-check.md"]),
    "has_module": ("Create agent-check.mjs.", ["agent-check.mjs"]),
    "note_title": ("Include a Markdown heading in the note.", ["agent-check.md"]),
    "note_purpose": ("Include a prose paragraph explaining the purpose.", ["agent-check.md"]),
    "three_checklist_items": ("Include at least three checklist items.", ["agent-check.md"]),
    "exports_ok_status": ("Export a constant named status whose value is \"ok\".", ["agent-check.mjs"]),
    "module_syntax": ("Fix module syntax reported by node --check.", ["agent-check.mjs"]),
    # Structured validation.
    "has_report": ("Create health-report.json.", ["health-report.json"]),
    "has_validator": ("Create validate-report.mjs.", ["validate-report.mjs"]),
    "valid_json_object": ("Write a valid JSON object for the report.", ["health-report.json"]),
    "status_ok": ("Set report status to 'ok'.", ["health-report.json"]),
    "two_named_checks": ("Include at least two check objects with nonempty name strings.", ["health-report.json"]),
    "generated_for": ("Include a nonempty generated_for string.", ["health-report.json"]),
    "validator_accepts_valid": ("The validator must exit 0 for the valid report.", ["validate-report.mjs"]),
    "validator_prints_success": ("Print a short success message when the report is valid.", ["validate-report.mjs"]),
    "validator_rejects_bad_status": ("The validator must reject a report whose status is 'bad'.", ["validate-report.mjs"]),
    "validator_rejects_bad_shape": ("The validator must reject an empty checks array.", ["validate-report.mjs"]),
    "validator_rejects_unnamed_check": ("The validator must reject a check without a name.", ["validate-report.mjs"]),
    "validator_rejects_missing_generated_for": ("The validator must reject a report without generated_for.", ["validate-report.mjs"]),
}


def findings_for(checks, infrastructure=None, evidence=None):
    result = []
    for key, passed in checks.items():
        if passed:
            continue
        fallback = ("Requirement failed: " + key.replace("_", " "), [])
        if key.startswith("has_") and "." in key:
            fallback = ("Create required file " + key[4:], [key[4:]])
        message, artifacts = DETAILS.get(key, fallback)
        finding = {"id": key, "message": message, "artifacts": list(artifacts),
                   "kind": "infrastructure" if key in (infrastructure or []) else "requirement"}
        if evidence and evidence.get(key):
            finding["evidence"] = str(evidence[key])[:300]
        result.append(finding)
    return result
