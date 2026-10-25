// The logo loader plays on a visitor's first page of the session only (chrome.css .g-seen): loaded in <head>, before
// the first paint, so coming back to Grid from Info or Proof does not flash it.
"use strict";
try {
  if (sessionStorage.getItem("griddy-seen")) document.documentElement.classList.add("g-seen");
  sessionStorage.setItem("griddy-seen", "1");
} catch (e) { /* private mode: the loader simply plays */ }
