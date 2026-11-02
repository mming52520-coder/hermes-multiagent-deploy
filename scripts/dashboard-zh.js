/* First visit to this Chinese package uses Hermes' built-in Simplified Chinese. */
(function () {
  "use strict";
  document.documentElement.lang = "zh-CN";
  try {
    const marker = "hermes-workflow-zh-initialized";
    if (localStorage.getItem(marker) !== "1") {
      localStorage.setItem("hermes-locale", "zh");
      localStorage.setItem(marker, "1");
    }
  } catch (_) {
    // If storage is disabled, the native language picker still works this visit.
  }
})();
