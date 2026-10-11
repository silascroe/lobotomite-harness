"""Actionable checker descriptions; grades remain the original boolean checks."""

DETAILS = {
    "semantic_main": ("Put the primary content inside a main element.", "index.html"),
    "has_semantic_sections": ("Include header, main, and form elements.", "index.html"),
    "responsive_css": ("Add a small-screen layout rule using a media query.", "styles.css"),
    "has_responsive_css": ("Add a small-screen layout rule using a media query.", "styles.css"),
    "focus_style": ("Add a visible keyboard focus style with :focus or :focus-visible.", "styles.css"),
    "has_focus_style": ("Add a visible keyboard focus style with :focus or :focus-visible.", "styles.css"),
    "signal_garden_heading": ("Include an h1 headed Signal Garden.", "index.html"),
    "description": ("Include a paragraph describing the page.", "index.html"),
    "button_and_status": ("Include a button and a status element with id/role status or aria-live.", "index.html"),
    "local_assets": ("Link local styles.css and app.js, without remote assets.", "index.html"),
    "links_css": ("Link styles.css from the page.", "index.html"),
    "links_js": ("Load app.js from the page.", "index.html"),
    "has_observation_fields": ("Provide title, location and note observation fields.", "index.html"),
    "click_handler": ("Register a click event handler for the page button.", "app.js"),
    "updates_status": ("Select the status element and update its content or attributes.", "app.js"),
    "script_syntax": ("Fix the JavaScript syntax reported by node --check.", "app.js"),
    "handles_submit": ("Register a submit event handler for the observation form.", "app.js"),
    "updates_count_or_cards": ("Implement observation count or card updates.", "app.js"),
    "has_note": ("Create agent-check.md.", "agent-check.md"),
    "has_module": ("Create agent-check.mjs.", "agent-check.mjs"),
    "note_title": ("Include a Markdown heading in the note.", "agent-check.md"),
    "note_purpose": ("Include a prose paragraph explaining the purpose.", "agent-check.md"),
    "three_checklist_items": ("Include at least three checklist items.", "agent-check.md"),
    "exports_ok_status": ("Export const or let status with value 'ok'.", "agent-check.mjs"),
    "module_syntax": ("Fix module syntax reported by node --check.", "agent-check.mjs"),
    "has_report": ("Create health-report.json.", "health-report.json"),
    "has_validator": ("Create validate-report.mjs.", "validate-report.mjs"),
    "valid_json_object": ("Write a valid JSON object for the report.", "health-report.json"),
    "status_ok": ("Set report status to 'ok'.", "health-report.json"),
    "two_named_checks": ("Include at least two check objects with nonempty name strings.", "health-report.json"),
    "generated_for": ("Include a nonempty generated_for string.", "health-report.json"),
    "validator_accepts_valid": ("The validator must exit 0 for the valid report.", "validate-report.mjs"),
    "validator_rejects_bad_status": ("The validator must reject a report whose status is 'bad'.", "validate-report.mjs"),
    "validator_rejects_bad_shape": ("The validator must reject an empty checks array.", "validate-report.mjs"),
}


def findings_for(checks, infrastructure=None):
    result = []
    for key, passed in checks.items():
        if passed:
            continue
        fallback = ("Requirement failed: " + key.replace("_", " "), None)
        if key.startswith("has_") and "." in key:
            fallback = ("Create required file " + key[4:], key[4:])
        message, artifact = DETAILS.get(key, fallback)
        result.append({"id": key, "message": message, "artifacts": [artifact] if artifact else [],
                       "kind": "infrastructure" if key in (infrastructure or []) else "requirement"})
    return result
