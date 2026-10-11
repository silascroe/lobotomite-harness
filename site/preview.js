const modeTabs = [...document.querySelectorAll("[data-preview-mode]")];
const inspector = document.getElementById("previewInspector");
const layout = document.getElementById("previewLayout");
const inspectorToggle = document.getElementById("inspectorToggle");
const inspectorClose = document.getElementById("inspectorClose");
const desktopLayout = window.matchMedia("(min-width: 1181px)");
let inspectorWasManuallySet = false;

function selectMode(mode, moveFocus = false) {
  const isRuns = mode === "runs";
  document.getElementById("runNavigation").hidden = !isRuns;
  document.getElementById("chatNavigation").hidden = isRuns;
  document.getElementById("runView").hidden = !isRuns;
  document.getElementById("chatView").hidden = isRuns;

  modeTabs.forEach((tab) => {
    const selected = tab.dataset.previewMode === mode;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && moveFocus) tab.focus();
  });
}

function setInspectorOpen(open, scrollToInspector = false) {
  inspector.hidden = !open;
  layout.classList.toggle("inspector-closed", !open);
  inspectorToggle.setAttribute("aria-expanded", String(open));
  if (scrollToInspector && open && !desktopLayout.matches) {
    inspector.scrollIntoView({ behavior: "smooth", block: "start" });
    inspectorClose.focus({ preventScroll: true });
  }
}

modeTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectMode(tab.dataset.previewMode));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const targetIndex = event.key === "Home" ? 0
      : event.key === "End" ? modeTabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : modeTabs.length - 1)) % modeTabs.length;
    selectMode(modeTabs[targetIndex].dataset.previewMode, true);
  });
});

inspectorToggle.addEventListener("click", () => {
  inspectorWasManuallySet = true;
  const opening = inspector.hidden;
  setInspectorOpen(opening, opening);
});

inspectorClose.addEventListener("click", () => {
  inspectorWasManuallySet = true;
  setInspectorOpen(false);
  inspectorToggle.focus();
});

desktopLayout.addEventListener("change", (event) => {
  if (!inspectorWasManuallySet) setInspectorOpen(event.matches);
});

selectMode("runs");
setInspectorOpen(desktopLayout.matches);
