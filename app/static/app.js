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
