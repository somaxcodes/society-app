// Briefly highlights whatever element the current URL fragment (#complaint-7)
// points at, so jumping to a linked/duplicate report via an anchor link is
// obvious at a glance instead of the user having to spot a plain-looking row
// among many identical ones.
function highlightFragmentTarget() {
    if (!window.location.hash) {
        return;
    }

    const target = document.querySelector(window.location.hash);
    if (!target) {
        return;
    }

    // Remove-then-reflow-then-add restarts the CSS animation even if the
    // same link is clicked twice in a row (the class would otherwise
    // already be present, so re-adding it alone wouldn't trigger it again).
    target.classList.remove("highlight-flash");
    void target.offsetWidth;
    target.classList.add("highlight-flash");
}

window.addEventListener("DOMContentLoaded", highlightFragmentTarget);
// Clicking a same-page anchor link (href="#complaint-7") doesn't reload the
// page, so DOMContentLoaded won't fire again — hashchange is what catches
// that case.
window.addEventListener("hashchange", highlightFragmentTarget);

// A dropdown that still lets you check several boxes at once — the staff
// complaints filter needs real multi-select (pick plumbing AND electrical),
// but a native <select multiple> needs Ctrl/Cmd+click to pick more than one,
// which isn't discoverable for non-technical users. This is a plain button
// that reveals a checkbox list in a popover instead; the checkboxes
// themselves are the real, unmodified <input name="category">/<input
// name="status"> form fields the backend already expects — this only
// changes how they're SHOWN, not what gets submitted.
function initDropdownFilters() {
    const dropdowns = document.querySelectorAll(".dropdown-filter");

    dropdowns.forEach((dropdown) => {
        const toggle = dropdown.querySelector(".dropdown-filter-toggle");
        const panel = dropdown.querySelector(".dropdown-filter-panel");
        const label = toggle.dataset.label;
        const checkboxes = panel.querySelectorAll('input[type="checkbox"], input[type="radio"]');
        // A single-choice list (the sort order) shows the chosen option's
        // own name on the button and closes after a pick, instead of the
        // "Label (N)" count the multi-select filters use.
        const isSingleChoice = panel.querySelector('input[type="radio"]') !== null;

        function updateToggleText() {
            if (isSingleChoice) {
                const chosen = Array.from(checkboxes).find((input) => input.checked);
                toggle.textContent = chosen ? chosen.parentElement.textContent.trim() : label;
                return;
            }
            const checkedCount = Array.from(checkboxes).filter((cb) => cb.checked).length;
            toggle.textContent = checkedCount > 0 ? `${label} (${checkedCount})` : `${label}: All`;
        }

        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            const willOpen = panel.hidden;
            // Only one popover open at a time — close any other dropdown's
            // panel before opening this one.
            document.querySelectorAll(".dropdown-filter-panel").forEach((otherPanel) => {
                otherPanel.hidden = true;
            });
            panel.hidden = !willOpen;
            toggle.setAttribute("aria-expanded", String(willOpen));
        });

        checkboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
            updateToggleText();
            if (isSingleChoice) {
                panel.hidden = true;
                toggle.setAttribute("aria-expanded", "false");
            }
        }));

        // Reflects whatever's already checked on page load — important
        // because the server re-renders these checkboxes as checked based
        // on the current ?category=...&status=... URL, so the toggle
        // button's label has to match that on first paint, not just after
        // a click.
        updateToggleText();
    });

    // Clicking anywhere outside an open dropdown closes it.
    document.addEventListener("click", (event) => {
        document.querySelectorAll(".dropdown-filter").forEach((dropdown) => {
            if (!dropdown.contains(event.target)) {
                dropdown.querySelector(".dropdown-filter-panel").hidden = true;
            }
        });
    });
}

window.addEventListener("DOMContentLoaded", initDropdownFilters);
