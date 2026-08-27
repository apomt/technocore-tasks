"use strict";

document.querySelectorAll(".mono").forEach((element) => {
  element.title = element.textContent.trim();
});
